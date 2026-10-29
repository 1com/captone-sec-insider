"""Layer 4, family A: price and trading features per row of `feature.row`, from the company's daily
prices with glitch days left out, and SPY's (v1's definitions). Windows count the company's own
price days.

- `ret_1m`, `ret_3m`, `ret_6m`: adjusted-close return over 21, 63, 126 days; `ret_12_1`: from 252
  to 21 days back.
- `vol_21`, `vol_63`, `vol_252`: annualised standard deviation of daily log returns (at least 15,
  40, 150 returns); `range_vol_21`: Parkinson's high-low estimate over 21 days.
- `max_drawdown_252`: the deepest fall from a running high within the last 252 days (at least
  63); `near_high_252`: adjusted close over its 252-day high.
- `beta_252`, `idio_vol_252`: against SPY's daily log returns over 252 days (at least 150).
- `log_close`; `log_addv20`: log(1 + average dollar volume over 20 days); `zero_volume_63`: share of
  the last 63 days without volume; `sessions_listed`: price days so far, capped at 1,260.

Kept beside them for other families, the row rules and the labels: `close`, `addv20`,
`cum_split_after`.
"""

import math

import duckdb
import numpy as np
import pandas as pd

from sentinel import db
from sentinel.config import Paths

CHUNK = 400  # companies per batch
ANNUAL = math.sqrt(252)
PRICE_FEATURES = [
    "ret_1m", "ret_3m", "ret_6m", "ret_12_1", "vol_21", "vol_63", "vol_252", "range_vol_21",
    "max_drawdown_252", "near_high_252", "beta_252", "idio_vol_252", "log_close", "log_addv20",
    "zero_volume_63", "sessions_listed",
]  # fmt: skip
PRICE_EXTRAS = ["close", "addv20", "cum_split_after"]


def spy_returns(con: duckdb.DuckDBPyConnection) -> pd.Series:
    """SPY's daily log returns (adjusted close), indexed by session (as timestamps)."""
    spy = con.execute(
        "select session, adj_close from stg_yahoo.price where ticker = 'SPY' and adj_close > 0 "
        "order by session"
    ).df()
    spy["session"] = pd.to_datetime(spy["session"])
    return np.log(spy.set_index("session")["adj_close"]).diff()


def one_company(g: pd.DataFrame, at: np.ndarray, spy: pd.Series) -> pd.DataFrame:
    """Family A for one company's daily rows `g` (sorted by session), at the sessions `at`."""
    s = g.set_index("session")
    adj = s["adj_close"]
    lr = np.log(adj).diff()
    f = pd.DataFrame(index=s.index)
    for name, n in (("ret_1m", 21), ("ret_3m", 63), ("ret_6m", 126)):
        f[name] = adj / adj.shift(n) - 1
    f["ret_12_1"] = adj.shift(21) / adj.shift(252) - 1
    for name, n, least in (("vol_21", 21, 15), ("vol_63", 63, 40), ("vol_252", 252, 150)):
        f[name] = lr.rolling(n, min_periods=least).std() * ANNUAL
    ok = (s["high"] > 0) & (s["low"] > 0) & (s["high"] >= s["low"])
    hl2 = np.where(ok, np.log(s["high"].where(ok) / s["low"].where(ok)) ** 2, np.nan)
    f["range_vol_21"] = (
        np.sqrt(
            pd.Series(hl2, index=s.index).rolling(21, min_periods=15).mean() / (4 * math.log(2))
        )
        * ANNUAL
    )
    f["near_high_252"] = adj / adj.rolling(252, min_periods=63).max()
    market = spy.reindex(s.index)
    cov = lr.rolling(252, min_periods=150).cov(market)
    var_m = market.rolling(252, min_periods=150).var()
    var_i = lr.rolling(252, min_periods=150).var()
    beta = cov / var_m
    f["beta_252"] = beta
    f["idio_vol_252"] = np.sqrt((var_i - beta**2 * var_m).clip(lower=0)) * ANNUAL
    f["log_close"] = np.log(s["close"])
    f["addv20"] = s["dollar_volume"].rolling(20, min_periods=15).mean()
    f["log_addv20"] = np.log1p(f["addv20"])
    f["zero_volume_63"] = (s["volume"] == 0).astype(float).rolling(63, min_periods=40).mean()
    f["sessions_listed"] = np.minimum(np.arange(1, len(s) + 1), 1260)
    f["close"] = s["close"]
    f["cum_split_after"] = s["cum_split_after"]
    keep = np.isin(s.index.values, at)
    a = adj.to_numpy()
    drawdowns = []
    for p in np.flatnonzero(keep):
        w = a[max(0, p - 251) : p + 1]
        drawdowns.append((w / np.maximum.accumulate(w)).min() - 1 if len(w) >= 63 else np.nan)
    out = f[keep].copy()
    out["max_drawdown_252"] = drawdowns
    out.insert(0, "cik", g["cik"].iloc[0])
    return out.reset_index().rename(columns={"session": "as_of"})


def build_price(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["feature.row", "core.price_daily", "stg_yahoo.price"], "feature.price")
    spy = spy_returns(con)
    ciks = [r[0] for r in con.execute("select distinct cik from feature.row order by 1").fetchall()]
    columns = ["cik", "as_of", *PRICE_FEATURES, *PRICE_EXTRAS]
    with db.transaction(con):
        con.execute(
            "create or replace table feature.price (cik VARCHAR, as_of DATE, "
            + ", ".join(f"{c} DOUBLE" for c in [*PRICE_FEATURES, *PRICE_EXTRAS])
            + ")"
        )
        for i in range(0, len(ciks), CHUNK):
            chunk = [ciks[i : i + CHUNK]]
            daily = con.execute(
                """
                select cik, session, close, high, low, volume, adj_close, dollar_volume,
                       cum_split_after
                from core.price_daily
                where not glitch and adj_close > 0 and close > 0
                  and cik in (select unnest(?::VARCHAR[]))
                order by cik, session
                """,
                chunk,
            ).df()
            rows = con.execute(
                "select cik, as_of from feature.row where cik in (select unnest(?::VARCHAR[]))",
                chunk,
            ).df()
            at = {c: pd.to_datetime(g["as_of"]).to_numpy(dtype="datetime64[ns]")
                  for c, g in rows.groupby("cik")}  # fmt: skip
            daily["session"] = pd.to_datetime(daily["session"])
            parts = [one_company(g, at[c], spy) for c, g in daily.groupby("cik", sort=False)
                     if c in at]  # fmt: skip
            if parts:
                frame = pd.concat(parts, ignore_index=True)[columns]
                frame["as_of"] = frame["as_of"].dt.date
                con.register("_chunk", frame)
                con.execute("insert into feature.price select * from _chunk")
                con.unregister("_chunk")
            done = min(i + CHUNK, len(ciks))
            if done % 4000 < CHUNK or done == len(ciks):
                echo(f"  price features: {done:,}/{len(ciks):,} companies")
    n = db.count(con, "feature.price")
    return {"price": n}
