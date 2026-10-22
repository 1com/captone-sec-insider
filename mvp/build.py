"""`python -m mvp build`: universe → prices → insider extract → returns → study → features → model
→ companies → render. Outcomes exist only for pilot events (constitution, Prototype Exception)."""

import json
from datetime import UTC, datetime

import duckdb
import numpy as np
import pandas as pd

from mvp.config import ARTIFACT, SITE, WORK, ensure_dirs, load_settings
from mvp.pipeline import companies as company_data
from mvp.pipeline import features as feats
from mvp.pipeline import model as pilot_model
from mvp.pipeline import prices as px
from mvp.pipeline import sic as sic_codes
from mvp.pipeline.insider import OUT as INSIDER_FILE
from mvp.pipeline.insider import extract
from mvp.pipeline.pricecheck import price_check
from mvp.pipeline.returns import event_returns
from mvp.pipeline.study import summarize
from mvp.pipeline.universe import SCRATCH_DB, build_universe, tickers_to_price
from mvp.util import json_safe, text_or_empty


def _funnel(events: pd.DataFrame, ret: pd.DataFrame) -> list[dict]:
    con = duckdb.connect(str(SCRATCH_DB), read_only=True)
    filings = con.execute("select count(*) from p_submission").fetchone()[0]
    purchases = con.execute("select count(*) from p_gated where g_purchase").fetchone()[0]
    clean = con.execute("select count(*) from p_clean_filing").fetchone()[0]
    con.close()
    pilot = events[events["sample"] == "pilot"]
    used = ret["priced"].fillna(False) & ret["passes_floors"].fillna(False)
    return [
        {"stage": "Quarterly SEC insider data sets", "n": 83, "note": "2006 Q1 – 2026 Q3"},
        {"stage": "Insider filings (Forms 3, 4, 5)", "n": int(filings), "note": "all forms"},
        {"stage": "Open-market purchase lines", "n": int(purchases), "note": "Form 4 code P"},
        {"stage": "Clean purchase filings", "n": int(clean), "note": "pilot gates"},
        {
            "stage": "Insider events, all years",
            "n": int(len(events)),
            "note": "clusters + solo CEO/CFO",
        },
        {
            "stage": "Pilot events 2006–2011",
            "n": int(len(pilot)),
            "note": "outside the study window",
        },
        {
            "stage": "…at companies still listed",
            "n": int(pilot["listed"].sum()),
            "note": "Yahoo coverage",
        },
        {
            "stage": "…priced and tradable",
            "n": int(used.sum()),
            "note": "$2, liquidity and price-check (G8) floors",
        },
    ]


def _coverage(events: pd.DataFrame, ret: pd.DataFrame) -> dict:
    pilot = events[events["sample"] == "pilot"]
    out = {}
    for g in ("A", "B1"):
        sel = ret["group"] == g
        out[g] = {
            "events": int((pilot["group"] == g).sum()),
            "listed": int((pilot["listed"] & (pilot["group"] == g)).sum()),
            "priced": int((ret["priced"].fillna(False) & sel).sum()),
            "used": int(
                (ret["priced"].fillna(False) & ret["passes_floors"].fillna(False) & sel).sum()
            ),
        }
        out[g]["share"] = out[g]["used"] / out[g]["events"] if out[g]["events"] else 0
    return out


def _screener(events, features, scores, g8_fail, calendar, horizon) -> list[dict]:
    """Recent events for the screener. Elapsed time uses the trading calendar only (no prices
    of the stock, no outcomes): sessions after the filing date up to the latest session."""
    as_of = calendar[-1]
    recent = events[events["sample"] == "recent"].copy()
    recent = recent.merge(
        features[["event_id", "f04_ceo_cfo", "f05_directors", "f06_ten_pct"]],
        on="event_id",
        how="left",
    )
    if len(scores):
        recent = recent.merge(scores, on="event_id", how="left")
    rows = []
    for r in recent.sort_values(["signal_date", "total_value_usd"], ascending=False).itertuples():
        score = getattr(r, "score", np.nan)
        elapsed = len(calendar) - int(calendar.searchsorted(pd.Timestamp(r.signal_date), "right"))
        rows.append(
            {
                "id": r.event_id,
                "date": str(r.signal_date),
                "cik": r.issuer_cik,
                "name": r.name,
                "ticker": text_or_empty(r.ticker),
                "group": r.group,
                "insiders": int(r.n_buyers),
                "value": float(r.total_value_usd),
                "ceo": int(r.f04_ceo_cfo) if pd.notna(r.f04_ceo_cfo) else 0,
                "dir": int(r.f05_directors) if pd.notna(r.f05_directors) else 0,
                "ten": int(r.f06_ten_pct) if pd.notna(r.f06_ten_pct) else 0,
                "score": None if pd.isna(score) else round(float(score), 4),
                "pct": None
                if pd.isna(getattr(r, "percentile", np.nan))
                else round(float(r.percentile), 3),
                "partial": bool(getattr(r, "partial", False)) if pd.notna(score) else False,
                "listed": bool(r.listed),
                "days_since": int((as_of - pd.Timestamp(r.signal_date)).days),
                "elapsed": int(elapsed),
                "left": int(max(horizon - elapsed, 0)),
                "window_open": bool(elapsed < horizon),
                "g8_fail": r.event_id in g8_fail,
            }
        )
    return rows


def run(skip_prices: bool, echo, timed) -> None:
    s = load_settings()
    ensure_dirs()
    with timed("universe"):
        events, companies = build_universe(s)
        events.to_parquet(WORK / "universe_events.parquet")
        companies.to_parquet(WORK / "companies.parquet")
    tickers = tickers_to_price(events)
    if not skip_prices:
        y = s.mvp["yahoo"]
        with timed("yahoo prices (cached)"):
            echo(
                "  "
                + str(
                    px.download(
                        tickers,
                        start=str(y["start"]),
                        batch_size=y["batch_size"],
                        retries=y["retries"],
                        pause=y["pause_seconds"],
                        echo=echo,
                    )
                )
            )
    if not INSIDER_FILE.exists():
        with timed("insider purchase/sale extract"):
            extract(s, echo=echo)
    with timed("load prices"):
        prices = px.load_many(tickers)
        echo(f"  {len(prices)} price series")

    with timed("price check G8 (reported price within the day's range ±10%)"):
        g8 = price_check(
            events[events["sample"].isin(["pilot", "recent"])].reset_index(drop=True), prices, s
        )
        g8_fail = set(g8.loc[~g8["passes_g8"], "event_id"])
        echo(f"  {len(g8_fail)} events fail the price check")
    with timed("industry codes for recent events (gate G7)"):
        recent_ev = events[events["sample"] == "recent"]
        sic_info = sic_codes.fetch(recent_ev["issuer_cik"].tolist(), s.research, echo=echo)
        g7_ciks = {c for c, v in sic_info.items() if sic_codes.excluded(v)}
        g7_events = set(recent_ev.loc[recent_ev["issuer_cik"].isin(g7_ciks), "event_id"])
        echo(f"  {len(g7_events)} recent events at funds, BDCs or blank-check companies excluded")
    pilot = events[events["sample"] == "pilot"].reset_index(drop=True)
    with timed("pilot returns (2006–2011 only)"):
        ret, paths, ks = event_returns(pilot, prices, s)
        bad = ret["event_id"].isin(g8_fail) & ret["priced"].fillna(False)
        ret.loc[bad, "passes_floors"] = False
        ret.loc[bad, "reason"] = "fails price check (G8)"
        ret.to_parquet(WORK / "pilot_returns.parquet")
        np.savez_compressed(WORK / "pilot_paths.npz", ks=ks, **paths)
    with timed("event study + bootstrap bands"):
        study = summarize(ret, paths, ks, s)
    scope = events[events["sample"].isin(["pilot", "recent"]) & events["listed"]]
    with timed("features (as of T)"):
        features = feats.build_features(scope.reset_index(drop=True), prices, s)
        features.to_parquet(WORK / "features.parquet")
    with timed("model: train 2006–2010, test 2011, score recent"):
        h = s.primary_horizon
        used = ret[ret["priced"].fillna(False) & ret["passes_floors"].fillna(False)]
        data = features.merge(
            used[["event_id", f"net_{h}_iwm", "window_end", "group"]], on="event_id", how="inner"
        )
        recent_ids = set(events.loc[events["sample"] == "recent", "event_id"])
        recent = features[features["event_id"].isin(recent_ids - g8_fail - g7_events)]
        model = pilot_model.run(data, recent, s)
        scores = model.pop("scores")
        scores.to_parquet(WORK / "scores.parquet")
        echo(
            f"  selected {model['selected']}; 2011 AUC "
            f"{model['results'][model['selected']]['auc']:.3f} vs baseline "
            f"{model['results']['baseline']['auc']:.3f}"
        )
    with timed("company profiles"):
        lookup = company_data.build(events, companies, scores, s, [SITE, ARTIFACT])
    funnel, coverage = _funnel(events, ret), _coverage(events, ret)
    calendar = prices["SPY"].index
    screener = _screener(
        events[~events["event_id"].isin(g7_events)], features, scores, g8_fail, calendar, h
    )
    context = {
        "meta": {
            "built": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "label": s.label,
            "disclaimer": s.mvp["disclaimer"],
            "horizon": h,
            "pilot": [str(s.pilot_start), str(s.pilot_end)],
            "recent": [str(s.recent_start), str(s.recent_end)],
            "shards": lookup["shards"],
            "companies": lookup["count"],
            "g7_excluded": len(g7_events),
            "as_of": str(calendar[-1].date()),
        },
        "funnel": funnel,
        "coverage": coverage,
        "study": study,
        "model": model,
        "screener": screener,
        "search": lookup["index"],
        "stats": {
            "cost_median": float(used["cost"].median()),
            "priced_tickers": len([t for t in prices if t not in ("IWM", "SPY")]),
        },
    }
    context = json_safe(context)
    (WORK / "dashboard.json").write_text(
        json.dumps(context, default=str, allow_nan=False), encoding="utf-8"
    )
    with timed("render dashboard (local + artifact)"):
        from mvp.site.render import render

        render(context, SITE, mode="local")
        render(context, ARTIFACT, mode="artifact")
    echo(f"done → {SITE / 'index.html'}  (serve: uv run python -m mvp serve)")
