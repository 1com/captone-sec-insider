"""Gate G8 (plan §6.2): every reported purchase price must lie within the stock's as-traded range on
the trade date, ±10% (registered.g8_tolerance). Catches data-entry errors such as a $1.80 price
filed as $180,000. Events with any failing line are excluded from returns and are not scored.
"""

import duckdb
import numpy as np
import pandas as pd

from mvp.pipeline.universe import SCRATCH_DB
from sentinel.config import registered_value


def price_check(events: pd.DataFrame, prices: dict[str, pd.DataFrame], settings) -> pd.DataFrame:
    """Return event_id, g8_checked (lines that could be checked), g8_failed, passes_g8."""
    tol = float(registered_value(settings.research, "g8_tolerance"))
    acc = (
        events[["event_id", "member_accessions"]]
        .explode("member_accessions")
        .rename(columns={"member_accessions": "accession"})
        .dropna()
    )
    con = duckdb.connect(str(SCRATCH_DB), read_only=True)
    con.register("acc", acc)
    lines = con.execute("""
        select a.event_id, l.price, l.trans_date
        from acc a
        join p_gated g on g.accession = a.accession and g.passes
        join p_purchase_line l on l.accession = g.accession and l.line_sk = g.line_sk""").df()
    con.close()
    ticker = dict(zip(events["event_id"], events["ticker"], strict=True))
    rows = []
    for event_id, grp in lines.groupby("event_id"):
        df = prices.get(ticker.get(event_id)) if isinstance(ticker.get(event_id), str) else None
        checked = failed = 0
        if df is not None:
            factor = (df["unadj_close"] / df["close"]).to_numpy()
            lows, highs = df["low"].to_numpy(), df["high"].to_numpy()
            for price, day in zip(grp["price"], grp["trans_date"], strict=True):
                if pd.isna(price) or pd.isna(day):
                    continue
                pos = int(df.index.searchsorted(pd.Timestamp(day), side="right")) - 1
                if pos < 0 or not np.isfinite(lows[pos]) or not np.isfinite(highs[pos]):
                    continue
                checked += 1
                lo, hi = lows[pos] * factor[pos] * (1 - tol), highs[pos] * factor[pos] * (1 + tol)
                if not lo <= price <= hi:
                    failed += 1
        rows.append(
            {
                "event_id": event_id,
                "g8_checked": checked,
                "g8_failed": failed,
                "passes_g8": failed == 0,
            }
        )
    out = events[["event_id"]].merge(pd.DataFrame(rows), on="event_id", how="left")
    out["passes_g8"] = out["passes_g8"].fillna(True).astype(bool)
    return out.fillna({"g8_checked": 0, "g8_failed": 0})
