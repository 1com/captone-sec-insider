"""Layer 5: the three risk labels (risk_params v5 `labels:`; no blow-up label, V2-9). The step
refuses to run unless the registration lock holds (`labels.lock`).

Development only: a label is computed only when its whole window ends by
`development.last_window_end` (31 December 2022). Later rows stay unlabelled and later releases are
not listed: they are the sealed risk holdout, labelled once at the end (plan step 7).

- `label.volatility`, per month-end row of `feature.row`: the annualised standard deviation of
  daily log returns (adjusted close) over the next 63 sessions; missing with fewer than 50.
- `label.dilution`, per month-end row: 1 if split-adjusted shares outstanding (as first filed) rise
  by 10% or more between the last count filed by the month-end and the last count filed within the
  next 182 days; missing if no new count is filed in that time.
- `label.results_move`, per results release (`core.results_release`) with a usable report date:
  the market-adjusted absolute move from the close of the session before the report date to the
  close of the session after the 8-K's filing date (`as_of` is the first, the release-eve row of
  `feature.row`), with the mean of the company's previous four moves (the naive baseline).
  Releases without the company's and SPY's closes on exactly those two sessions are left out and
  do not enter later baselines.

Glitch days are left out of every price-based label. Each row carries the date its window ends, to
purge the walk-forward folds.
"""

import math
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from sentinel import db
from sentinel.config import Paths, risk_params
from sentinel.labels import lock

CHUNK = 400  # companies per batch
MONTH_COLUMNS = ["cik", "as_of", "vol_63_future", "vol_window_end", "dilution",
                 "dilution_window_end"]  # fmt: skip


def _days(x) -> np.ndarray:
    return pd.to_datetime(pd.Series(x)).to_numpy(dtype="datetime64[ns]")


def _at(days: np.ndarray, values: np.ndarray, when: np.datetime64) -> float:
    """The value on session `when` exactly, else NaN."""
    k = np.searchsorted(days, when)
    return values[k] if k < len(days) and days[k] == when else np.nan


def _asof(days: np.ndarray, values: np.ndarray, when) -> np.ndarray:
    """The value on the last session on or before each `when`, else NaN."""
    k = np.searchsorted(days, when, side="right") - 1
    return np.where(k >= 0, values[np.clip(k, 0, None)], np.nan)


def share_steps(shares: pd.DataFrame) -> pd.DataFrame:
    """Per company, the counts in filing order that bring a newer period (`filed`, `period_end`,
    `value`): what was known when, as first filed."""
    out = []
    for _, g in shares.sort_values(["cik", "filed", "period_end"]).groupby("cik", sort=False):
        newest = g["period_end"].cummax().shift()
        out.append(g[newest.isna() | (g["period_end"] > newest)])
    return pd.concat(out) if out else shares.iloc[0:0]


def month_labels(daily: pd.DataFrame, rows: pd.DataFrame, calendar: np.ndarray,
                 steps: pd.DataFrame, rules: dict, last_end: date) -> pd.DataFrame:  # fmt: skip
    """Volatility and dilution labels for a batch of companies. `daily`: (cik, session, adj_close,
    cum_split_after), glitch days removed; `rows`: (cik, as_of) month-ends; `calendar`: every
    session, sorted; `steps`: `share_steps` of the batch's share counts."""
    vol, dil = rules["labels"]["volatility"], rules["labels"]["dilution"]
    vol_n, vol_min = int(vol["window_sessions"]), int(vol["min_returns"])
    dil_days, dil_min = int(dil["window_days"]), float(dil["min_increase"])
    last_end = np.datetime64(pd.Timestamp(last_end), "ns")
    by_cik = {cik: g for cik, g in daily.groupby("cik", sort=False)}
    by_steps = {cik: g for cik, g in steps.groupby("cik", sort=False)}
    out = []
    for cik, r in rows.groupby("cik", sort=False):
        g = by_cik.get(cik)
        if g is None:
            continue
        g = g.sort_values("session")
        days = _days(g["session"])
        pos = np.searchsorted(calendar, days)  # each price day's place in the calendar
        adj = g["adj_close"].to_numpy()
        lr = np.diff(np.log(adj))
        sh = by_steps.get(cik)
        if sh is not None:
            filed = _days(sh["filed"])
            count = sh["value"].to_numpy(dtype=float)
            split = _asof(days, g["cum_split_after"].to_numpy(dtype=float), _days(sh["period_end"]))
        for t in _days(r["as_of"]):
            t_pos = np.searchsorted(calendar, t)
            k = np.searchsorted(pos, t_pos)
            if t_pos >= len(calendar) or k >= len(pos) or pos[k] != t_pos:
                continue  # no price on this day
            row = dict.fromkeys(MONTH_COLUMNS[2:]) | {"cik": cik, "as_of": pd.Timestamp(t).date()}
            end = t_pos + vol_n
            if end < len(calendar) and calendar[end] <= last_end:
                row["vol_window_end"] = pd.Timestamp(calendar[end]).date()
                hi = np.searchsorted(pos, end, side="right")
                rets = lr[k : hi - 1]  # the returns into the price days after t, up to `end`
                if len(rets) >= vol_min:
                    row["vol_63_future"] = float(np.std(rets, ddof=1) * math.sqrt(252))
            horizon = t + np.timedelta64(dil_days, "D")
            if horizon <= last_end:
                row["dilution_window_end"] = pd.Timestamp(horizon).date()
                if sh is not None:
                    i0 = np.searchsorted(filed, t, side="right") - 1
                    i1 = np.searchsorted(filed, horizon, side="right") - 1
                    if i0 >= 0 and i1 > i0 and count[i0] > 0 and split[i1] > 0:
                        before = count[i0] * split[i0] / split[i1]  # in the later count's shares
                        if np.isfinite(before):
                            row["dilution"] = float(count[i1] >= (1 + dil_min) * before)
            if row["vol_window_end"] or row["dilution_window_end"]:
                out.append(row)
    return pd.DataFrame(out, columns=MONTH_COLUMNS)


def results_moves(
    daily: pd.DataFrame, releases: pd.DataFrame, calendar: np.ndarray, spy: pd.DataFrame,
    last_end: date, max_gap_days: int,
) -> pd.DataFrame:  # fmt: skip
    """`label.results_move` rows for a batch of companies (see the module docstring)."""
    last_end = np.datetime64(pd.Timestamp(last_end), "ns")
    spy_days, spy_adj = _days(spy["session"]), spy["adj_close"].to_numpy(dtype=float)
    by_cik = {cik: g for cik, g in daily.groupby("cik", sort=False)}
    out = []
    for cik, ev in releases.groupby("cik", sort=False):
        g = by_cik.get(cik)
        if g is None:
            continue
        g = g.sort_values("session")
        days, adj = _days(g["session"]), g["adj_close"].to_numpy(dtype=float)
        moves: list[float] = []
        ev = ev.sort_values("filing_date")
        for filed, released in zip(_days(ev["filing_date"]), _days(ev["report_date"]),
                                   strict=True):  # fmt: skip
            if (pd.isna(released) or released > filed
                    or filed - released > np.timedelta64(max_gap_days, "D")):  # fmt: skip
                continue
            p0 = np.searchsorted(calendar, released, side="left") - 1
            p1 = np.searchsorted(calendar, filed, side="right")
            if p0 < 0 or p1 >= len(calendar):
                continue
            t0, t1 = calendar[p0], calendar[p1]
            if t1 > last_end:
                break
            a0, a1 = _at(days, adj, t0), _at(days, adj, t1)
            s0, s1 = _at(spy_days, spy_adj, t0), _at(spy_days, spy_adj, t1)
            if not np.isfinite([a0, a1, s0, s1]).all():
                continue
            move = abs((a1 / a0 - 1) - (s1 / s0 - 1))
            out.append({
                "cik": cik, "filing_date": pd.Timestamp(filed).date(),
                "report_date": pd.Timestamp(released).date(), "as_of": pd.Timestamp(t0).date(),
                "close_after": pd.Timestamp(t1).date(), "move": float(move),
                "prev4_mean": float(np.mean(moves[-4:])) if moves else None,
                "n_prev": len(moves),
            })  # fmt: skip
            moves.append(move)
    return pd.DataFrame(out, columns=["cik", "filing_date", "report_date", "as_of", "close_after",
                                      "move", "prev4_mean", "n_prev"])  # fmt: skip


def build_labels(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["feature.row", "core.price_daily", "core.shares_outstanding",
                     "core.results_release", "ref.calendar", "stg_yahoo.price"],
               "label.volatility")  # fmt: skip
    try:
        lock.require(p)
    except lock.NotLocked as e:
        raise db.StepFailed(str(e)) from e
    rules = risk_params(p)
    last_end = rules["development"]["last_window_end"]
    gap = int(rules["labels"]["results_move"]["max_report_gap_days"])
    calendar = _days(con.execute("select session from ref.calendar order by 1").df()["session"])
    spy = con.execute("select session, adj_close from stg_yahoo.price where ticker = 'SPY' "
                      "and adj_close > 0 order by 1").df()  # fmt: skip
    ciks = [r[0] for r in con.execute(
        "select distinct cik from feature.row where month_end or release_eve order by 1"
    ).fetchall()]  # fmt: skip
    with db.transaction(con):
        con.execute("create or replace temp table _month (cik VARCHAR, as_of DATE, "
                    "vol_63_future DOUBLE, vol_window_end DATE, dilution DOUBLE, "
                    "dilution_window_end DATE)")  # fmt: skip
        con.execute(
            "create or replace table label.results_move (cik VARCHAR, filing_date DATE, "
            "report_date DATE, as_of DATE, close_after DATE, move DOUBLE, prev4_mean DOUBLE, "
            "n_prev INTEGER)"
        )
        for i in range(0, len(ciks), CHUNK):
            args = [ciks[i : i + CHUNK]]
            within = "cik in (select unnest(?::VARCHAR[]))"
            daily = con.execute(
                "select cik, session, adj_close, cum_split_after from core.price_daily "
                f"where not glitch and adj_close > 0 and close > 0 and {within}",
                args,
            ).df()
            rows = con.execute(f"select cik, as_of from feature.row where month_end and {within}",
                               args).df()  # fmt: skip
            shares = con.execute(
                "select cik, as_of as period_end, shares as value, filed "
                f"from core.shares_outstanding where {within}",
                args,
            ).df()
            for c in ("period_end", "filed"):
                shares[c] = pd.to_datetime(shares[c])
            releases = con.execute(
                f"select cik, filing_date, report_date from core.results_release where {within}",
                args,
            ).df()
            labels = month_labels(daily, rows, calendar, share_steps(shares), rules, last_end)
            moves = results_moves(daily, releases, calendar, spy, last_end, gap)
            for table, frame in (("_month", labels), ("label.results_move", moves)):
                if len(frame):
                    con.register("_chunk", frame)
                    con.execute(f"insert into {table} select * from _chunk")
                    con.unregister("_chunk")
            done = min(i + CHUNK, len(ciks))
            if done % 4000 < CHUNK or done == len(ciks):
                echo(f"  labels: {done:,}/{len(ciks):,} companies")
        con.execute(
            "create or replace table label.volatility as select cik, as_of, vol_63_future, "
            "vol_window_end as window_end from _month where vol_window_end is not null "
            "order by cik, as_of"
        )
        con.execute(
            "create or replace table label.dilution as select cik, as_of, dilution, "
            "dilution_window_end as window_end from _month where dilution_window_end is not null "
            "order by cik, as_of"
        )
        con.execute("drop table _month")
    counts = {}
    for name, col in (("volatility", "vol_63_future"), ("dilution", "dilution"),
                      ("results_move", "move")):  # fmt: skip
        n, labelled = con.execute(f"select count(*), count({col}) from label.{name}").fetchone()
        counts |= {f"{name}_rows": n, f"{name}_labelled": labelled}
    echo(f"  labels: {counts}")
    return counts
