"""Model features, all as of the session at T (research R6). Feature numbers follow plan §7.2.

Insider features come from the event's member filings (provisional scratch database) and from the
purchase/sale extract (holdings after each purchase, prior selling). Price features use Yahoo
prices up to and including the session at T, never later.
"""

import duckdb
import numpy as np
import pandas as pd

from mvp.config import WORK
from mvp.pipeline.returns import round_trip_cost, session_at
from mvp.pipeline.universe import SCRATCH_DB

INSIDER_FEATURES = {
    "f01_buyers": "Number of insiders buying",
    "f02_log_value": "Size of the purchase ($, log)",
    "f03_top_share": "Largest buyer's share of the total",
    "f04_ceo_cfo": "CEO/CFO buyers",
    "f05_directors": "Director buyers",
    "f06_ten_pct": "10% owner buyers",
    "f07_holdings_increase": "Increase in buyers' holdings (log)",
    "f08_new_positions": "Buyers opening a new position",
    "f11_filing_lag": "Days between trade and filing",
    "f12_prior_sales": "Insider selling in prior 90 days ($, log)",
    "f13_ceo_cfo_sold": "CEO/CFO sold in prior 90 days",
    "f14_repeat_buying": "Earlier insider buying in prior year",
}
MARKET_FEATURES = {
    "f17_log_addv": "Typical daily trading ($, log)",
    "f19_ret_1m": "Return over the prior month",
    "f20_momentum": "Return over the prior year (ex last month)",
    "f21_from_high": "Distance below the 52-week high",
    "f22_volatility": "Daily volatility (3 months)",
    "f23_spread": "Estimated bid–ask spread",
}
MIXED_FEATURES = {"f18_value_to_addv": "Purchase size vs typical daily trading (log)"}
ALL_FEATURES = {**INSIDER_FEATURES, **MIXED_FEATURES, **MARKET_FEATURES}


def _member_tables(events: pd.DataFrame):
    acc = (
        events[["event_id", "member_accessions"]]
        .explode("member_accessions")
        .rename(columns={"member_accessions": "accession"})
        .dropna()
    )
    con = duckdb.connect(str(SCRATCH_DB), read_only=True)
    con.register("acc", acc)
    filings = con.execute("""
        select a.event_id, c.accession, c.value_usd, c.owner_ciks, c.filing_date
        from acc a join p_clean_filing c using (accession)""").df()
    owners = con.execute("""
        select a.event_id, o.owner_cik, bool_or(o.is_ceo_cfo) ceo, bool_or(o.is_director) dir,
               bool_or(contains(o.relationship, 'TenPercentOwner')) ten
        from acc a join p_owner o using (accession)
        group by all""").df()
    lags = con.execute("""
        select a.event_id, avg(date_diff('day', l.trans_date, s.filing_date)) lag
        from acc a join p_gated g on g.accession = a.accession and g.passes
        join p_purchase_line l on l.accession = g.accession and l.line_sk = g.line_sk
        join p_submission s on s.accession = g.accession
        group by a.event_id""").df()
    clean = con.execute("select issuer_cik, filing_date from p_clean_filing").df()
    con.close()
    return acc, filings, owners, lags, clean


def _holdings(acc: pd.DataFrame) -> pd.DataFrame:
    """Per event: mean log holdings increase and number of new positions (F7, F8)."""
    con = duckdb.connect()
    con.register("acc", acc)
    per_filing = con.execute(f"""
        with lines as (
            select t.accession, t.direct_indirect, coalesce(t.nature, '') nature,
                   t.shares, t.shares_after, try_cast(t.line_sk as BIGINT) sk
            from '{WORK / "insider_tx.parquet"}' t
            where t.code = 'P' and t.acq_disp = 'A'
              and t.accession in (select accession from acc)
        ), holding as (
            select accession, direct_indirect, nature,
                   arg_max(shares_after, sk) held_after, sum(shares) bought
            from lines group by all
        )
        select accession, sum(held_after) held_after, sum(held_after - bought) held_before
        from holding group by accession""").df()
    df = acc.merge(per_filing, on="accession", how="inner")
    df["inc"] = np.log((df["held_after"].clip(lower=0) + 1) / (df["held_before"].clip(lower=0) + 1))
    df["new"] = (df["held_before"] <= 0).astype(int)
    return (
        df.groupby("event_id")
        .agg(f07_holdings_increase=("inc", "mean"), f08_new_positions=("new", "sum"))
        .reset_index()
    )


def _prior_sales(events: pd.DataFrame) -> pd.DataFrame:
    """Value of open-market insider sales at the issuer in the 90 days before T (F12, F13)."""
    con = duckdb.connect()
    ev = events[["event_id", "issuer_cik", "signal_date"]].copy()
    con.register("ev", ev)
    return con.execute(f"""
        select ev.event_id,
               ln(1 + coalesce(sum(t.value_usd), 0)) f12_prior_sales,
               coalesce(bool_or(t.is_ceo_cfo), false)::INTEGER f13_ceo_cfo_sold
        from ev left join '{WORK / "insider_tx.parquet"}' t
          on t.issuer_cik = ev.issuer_cik and t.code = 'S' and t.acq_disp = 'D'
         and t.filing_date >= ev.signal_date - interval 90 day
         and t.filing_date < ev.signal_date
        group by ev.event_id""").df()


def build_features(events: pd.DataFrame, prices: dict[str, pd.DataFrame], settings) -> pd.DataFrame:
    acc, filings, owners, lags, clean = _member_tables(events)
    out = events[
        ["event_id", "issuer_cik", "signal_date", "ticker", "n_buyers", "total_value_usd"]
    ].copy()
    out["f01_buyers"] = out["n_buyers"]
    out["f02_log_value"] = np.log(out["total_value_usd"].clip(lower=1))
    top = filings.groupby("event_id")["value_usd"].max()
    out["f03_top_share"] = out["event_id"].map(top) / out["total_value_usd"]
    agg = owners.groupby("event_id").agg(
        f04_ceo_cfo=("ceo", "sum"), f05_directors=("dir", "sum"), f06_ten_pct=("ten", "sum")
    )
    out = out.merge(agg.reset_index(), on="event_id", how="left")
    out = out.merge(_holdings(acc), on="event_id", how="left")
    out = out.merge(lags.rename(columns={"lag": "f11_filing_lag"}), on="event_id", how="left")
    out = out.merge(_prior_sales(events), on="event_id", how="left")

    clean["filing_date"] = pd.to_datetime(clean["filing_date"])
    by_issuer = {k: np.sort(g["filing_date"].to_numpy()) for k, g in clean.groupby("issuer_cik")}

    def repeat(row):
        dates = by_issuer.get(row.issuer_cik)
        if dates is None:
            return 0
        t = np.datetime64(pd.Timestamp(row.signal_date))
        lo, hi = t - np.timedelta64(365, "D"), t - np.timedelta64(13, "D")
        return int(np.searchsorted(dates, hi) - np.searchsorted(dates, lo))

    out["f14_repeat_buying"] = [repeat(r) for r in out.itertuples(index=False)]

    cal = prices["SPY"].index
    w, vol_w = settings.addv_window, settings.vol_window
    tick, cap = settings.mvp["cost"]["tick"], settings.mvp["cost"]["cap"]
    market = []
    for r in out.itertuples(index=False):
        rec = {"event_id": r.event_id}
        df = prices.get(r.ticker) if isinstance(r.ticker, str) else None
        if df is not None:
            s = df.reindex(cal)
            i_t = session_at(cal, r.signal_date)
            close = s["adj_close"].to_numpy()
            if i_t >= w and np.isfinite(s["close"].iat[i_t]):
                win = s.iloc[i_t - w + 1 : i_t + 1]
                addv = float((win["close"] * win["volume"]).mean())
                rec["f17_log_addv"] = np.log(max(addv, 1.0))
                rec["f18_value_to_addv"] = np.log(r.total_value_usd / max(addv, 1.0))
                rec["f23_spread"] = round_trip_cost(
                    s, i_t, w, float(s["unadj_close"].iat[i_t]), tick, cap
                )
                if i_t >= 21 and np.isfinite(close[i_t - 21]):
                    rec["f19_ret_1m"] = close[i_t] / close[i_t - 21] - 1
                if i_t >= 252 and np.isfinite(close[i_t - 252]):
                    rec["f20_momentum"] = close[i_t - 21] / close[i_t - 252] - 1
                hist = close[max(0, i_t - 251) : i_t + 1]
                if np.isfinite(hist).sum() > 120:
                    rec["f21_from_high"] = close[i_t] / np.nanmax(hist) - 1
                lr = np.diff(np.log(close[max(0, i_t - vol_w) : i_t + 1]))
                if np.isfinite(lr).sum() > vol_w // 2:
                    rec["f22_volatility"] = float(np.nanstd(lr))
        market.append(rec)
    out = out.merge(pd.DataFrame(market), on="event_id", how="left")
    for col in ALL_FEATURES:
        if col not in out:
            out[col] = np.nan
    return out[["event_id", "issuer_cik", "signal_date", "ticker", *ALL_FEATURES]]
