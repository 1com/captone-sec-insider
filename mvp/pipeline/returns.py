"""Pilot-sample event returns: floors, cost, abnormal-return paths and horizon BHARs (research R4).

Constitution, Prototype Exception: outcomes are computed ONLY for events with signal dates in the
pilot sample (2006–2011). `event_returns` raises PilotViolation for anything else.
"""

import numpy as np
import pandas as pd

from mvp.config import Settings, assert_pilot

BENCHMARKS = ("IWM", "SPY")


def abdi_ranaldo(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> float:
    """Close-high-low spread estimate (Abdi & Ranaldo, 2017) over a window of sessions."""
    c = np.log(close)
    eta = (np.log(high) + np.log(low)) / 2
    prod = (c[:-1] - eta[:-1]) * (c[:-1] - eta[1:])
    m = np.nanmean(prod) if np.isfinite(prod).any() else np.nan
    return float(np.sqrt(max(4 * m, 0.0))) if np.isfinite(m) else np.nan


def session_at(calendar: pd.DatetimeIndex, day) -> int:
    """Index of the last trading session on or before `day` (the SEC is open on some holidays)."""
    return int(calendar.searchsorted(pd.Timestamp(day), side="right")) - 1


def round_trip_cost(
    s: pd.DataFrame, i_t: int, window: int, unadj_close: float, tick: float, cap: float
) -> float:
    w = s.iloc[max(i_t - window, 0) : i_t + 1]
    est = abdi_ranaldo(w["close"].to_numpy(), w["high"].to_numpy(), w["low"].to_numpy())
    floor = tick / unadj_close if unadj_close and unadj_close > 0 else np.nan
    if not np.isfinite(est):
        est = floor
    return float(min(max(est, floor), cap))


def event_returns(events: pd.DataFrame, prices: dict[str, pd.DataFrame], settings: Settings):
    """Return (per-event table, {benchmark: abnormal path matrix}, k offsets).

    Entry is the open of the first session after the session at T. The path at offset k is the
    stock's cumulative return from the entry open to the close of session k, minus the benchmark's.
    """
    assert_pilot(events["signal_date"], settings)
    cal = prices["SPY"].index
    pre, post = settings.mvp["path"]["pre"], settings.mvp["path"]["post"]
    ks = np.arange(-pre, post + 1)
    floor_px, min_addv = settings.price_floor, settings.min_addv
    min_active, act_window = settings.activity
    addv_w = settings.addv_window
    tick, cap = settings.mvp["cost"]["tick"], settings.mvp["cost"]["cap"]

    bench = {}
    for b in BENCHMARKS:
        bdf = prices[b].reindex(cal)
        bench[b] = (
            bdf["adj_close"].ffill(limit=5).to_numpy(),
            (bdf["open"] * bdf["adj_close"] / bdf["close"]).to_numpy(),
        )

    paths = {b: np.full((len(events), len(ks)), np.nan) for b in BENCHMARKS}
    aligned: dict[str, pd.DataFrame] = {}
    rows = []
    for i, ev in enumerate(events.itertuples(index=False)):
        row = {"event_id": ev.event_id, "priced": False, "passes_floors": False, "reason": ""}
        df = prices.get(ev.ticker) if isinstance(ev.ticker, str) else None
        if df is None:
            row["reason"] = "no Yahoo data (not listed today or download failed)"
            rows.append(row)
            continue
        if ev.ticker not in aligned:
            aligned[ev.ticker] = df.reindex(cal)
        s = aligned[ev.ticker]
        i_t = session_at(cal, ev.signal_date)
        i_e = i_t + 1
        if (
            i_t < addv_w
            or i_e >= len(cal)
            or not (np.isfinite(s["close"].iat[i_t]) and np.isfinite(s["open"].iat[i_e]))
        ):
            row["reason"] = "Yahoo history does not cover the event"
            rows.append(row)
            continue
        unadj = float(s["unadj_close"].iat[i_t])
        w = s.iloc[i_t - addv_w + 1 : i_t + 1]
        addv = float((w["close"] * w["volume"]).mean())
        active = int((w["volume"].iloc[-act_window:] > 0).sum())
        passes = unadj >= floor_px and addv >= min_addv and active >= min_active
        cost = round_trip_cost(s, i_t, addv_w, unadj, tick, cap)

        adj = s["adj_close"].ffill(limit=5).to_numpy()
        entry_open = s["open"].iat[i_e] * s["adj_close"].iat[i_e] / s["close"].iat[i_e]
        idx = i_e + ks
        ok = (idx >= 0) & (idx < len(cal))
        stock = np.full(len(ks), np.nan)
        stock[ok] = adj[idx[ok]] / entry_open - 1
        for b in BENCHMARKS:
            badj, bopen = bench[b]
            br = np.full(len(ks), np.nan)
            br[ok] = badj[idx[ok]] / bopen[i_e] - 1
            paths[b][i] = stock - br

        row.update(
            {
                "priced": True,
                "passes_floors": bool(passes),
                "reason": "" if passes else "fails price, liquidity or activity floor",
                "session_t": cal[i_t].date(),
                "entry_date": cal[i_e].date(),
                "window_end": cal[min(i_e + settings.primary_horizon - 1, len(cal) - 1)].date(),
                "unadj_close_t": unadj,
                "addv20": addv,
                "active_sessions": active,
                "cost": cost,
            }
        )
        for h in settings.horizons:
            j = pre + h - 1
            row[f"raw_{h}"] = float(stock[j])
            for b in BENCHMARKS:
                gross = float(paths[b][i, j])
                row[f"gross_{h}_{b.lower()}"] = gross
                row[f"net_{h}_{b.lower()}"] = gross - cost
        rows.append(row)
    out = events[["event_id", "issuer_cik", "group", "signal_date", "ticker"]].merge(
        pd.DataFrame(rows), on="event_id", how="left"
    )
    return out, paths, ks
