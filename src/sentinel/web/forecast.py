"""The dilution forecast shown by the app (026, V2-61).

The approved model (V2-52) is the frozen object the holdout test scores (V2-59), loaded once from
MLflow. It scores every eligible company still trading from the serving copy's latest feature rows
(`app.company_card`), again whenever a new copy is published. For the MVP the scoring happens here;
it moves into the daily update (009) afterwards. The reasons are the trees' per-feature
contributions (LightGBM `pred_contrib`): how much each input moved this company's chance up or
down from the average, in the trees' log-odds."""

from __future__ import annotations

import json
import os
import threading

import numpy as np
import pandas as pd

from sentinel import config
from sentinel.models import dilution
from sentinel.scoring.daily import CURRENT_DAYS

# plain-English names of the model's inputs and how to show their values
FEATURES = {
    "ret_1m": ("Share price change, last month", "pct"),
    "ret_3m": ("Share price change, last 3 months", "pct"),
    "ret_6m": ("Share price change, last 6 months", "pct"),
    "ret_12_1": ("Share price change over the past year", "pct"),
    "vol_21": ("Price swings, last month (yearly rate)", "pct"),
    "vol_63": ("Price swings, last 3 months (yearly rate)", "pct"),
    "vol_252": ("Price swings, last year", "pct"),
    "range_vol_21": ("Daily high-low range, last month", "pct"),
    "max_drawdown_252": ("Largest fall from a peak, last year", "pct"),
    "near_high_252": ("Price compared with its 1-year high", "pct"),
    "beta_252": ("Moves with the market (beta)", "num"),
    "idio_vol_252": ("Company-specific price swings", "pct"),
    "log_close": ("Share price", "logprice"),
    "log_addv20": ("Average value traded per day", "logmoney"),
    "zero_volume_63": ("Days without trading, last 3 months", "num"),
    "sessions_listed": ("Trading days since listing", "count"),
    "close": ("Share price", "price"),
    "addv20": ("Average value traded per day", "money"),
    "market_cap": ("Market value of the company", "money"),
    "shares_outstanding": ("Shares outstanding", "count"),
    "log_market_cap": ("Market value of the company", "logmoney"),
    "book_to_market": ("Book value ÷ market value", "num"),
    "leverage": ("Liabilities ÷ assets", "num"),
    "cash_to_assets": ("Cash as a share of assets", "pct"),
    "cash_runway_years": ("Cash runway (years of losses covered)", "years"),
    "loss_making": ("Loss-making", "bool"),
    "revenue_growth": ("Revenue growth, 12 months", "pct"),
    "gross_margin": ("Gross margin", "pct"),
    "rd_intensity": ("Research spending ÷ revenue", "pct"),
    "interest_coverage": ("Operating profit ÷ interest paid", "num"),
    "current_ratio": ("Current assets ÷ current liabilities", "num"),
    "receivables_to_assets": ("Receivables as a share of assets", "pct"),
    "sbc_to_revenue": ("Stock pay to staff ÷ revenue", "pct"),
    "share_growth_12m": ("Share count change, last 12 months", "pct"),
    "issue_proceeds_to_assets": ("Cash raised from selling shares ÷ assets", "pct"),
    "months_since_report": ("Months since the last financial report", "num"),
    "n_agreement_3m": ("Material agreements (8-K 1.01), 3 months", "count"),
    "n_agreement_12m": ("Material agreements (8-K 1.01), 12 months", "count"),
    "n_acquisition_3m": ("Acquisitions or sales of assets, 3 months", "count"),
    "n_acquisition_12m": ("Acquisitions or sales of assets, 12 months", "count"),
    "n_bankruptcy_3m": ("Bankruptcy reports, 3 months", "count"),
    "n_bankruptcy_12m": ("Bankruptcy reports, 12 months", "count"),
    "n_delisting_notice_3m": ("Delisting notices, 3 months", "count"),
    "n_delisting_notice_12m": ("Delisting notices, 12 months", "count"),
    "n_unregistered_sale_3m": ("Private share sales (8-K 3.02), 3 months", "count"),
    "n_unregistered_sale_12m": ("Private share sales (8-K 3.02), 12 months", "count"),
    "n_auditor_change_3m": ("Auditor changes, 3 months", "count"),
    "n_auditor_change_12m": ("Auditor changes, 12 months", "count"),
    "n_restatement_3m": ("Restated financial statements, 3 months", "count"),
    "n_restatement_12m": ("Restated financial statements, 12 months", "count"),
    "n_exec_change_3m": ("Executive or director changes, 3 months", "count"),
    "n_exec_change_12m": ("Executive or director changes, 12 months", "count"),
    "n_late_filing_3m": ("Late-filing notices, 3 months", "count"),
    "n_late_filing_12m": ("Late-filing notices, 12 months", "count"),
    "n_offering_3m": ("Share offering filings, 3 months", "count"),
    "n_offering_12m": ("Share offering filings, 12 months", "count"),
    "n_shelf_effective_3m": ("Shelf registrations made effective, 3 months", "count"),
    "n_shelf_effective_12m": ("Shelf registrations made effective, 12 months", "count"),
    "n_activist_3m": ("Activist investor stakes (13D), 3 months", "count"),
    "n_activist_12m": ("Activist investor stakes (13D), 12 months", "count"),
    "n_8k_12m": ("Event reports (8-K), 12 months", "count"),
    "days_since_results": ("Days since the last results", "count"),
    "days_to_next_results": ("Days to the next expected results", "count"),
    "short_ratio_1m": ("Short-sale share of volume, last month", "pct"),
    "short_ratio_3m": ("Short-sale share of volume, last 3 months", "pct"),
    "short_ratio_chg": ("Change in the short-sale share", "pctpt"),
}


def _value(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)


class Forecasts:
    """The approved model's chance for every eligible company still trading, with its reasons."""

    def __init__(self, p: config.Paths | None = None):
        self.p = p or config.paths()
        self._lock = threading.Lock()
        self._model = None
        self.info: dict = {}
        self.card: dict = {}
        self.by_cik: dict[str, dict] = {}
        self.as_of: str | None = None
        self._version = None

    def _load(self) -> None:
        from sentinel import holdout  # MLflow is imported only when the app starts scoring

        frozen = holdout.frozen_models(self.p, ("dilution",))["dilution"]
        m = frozen["model"]
        tags = frozen["run"].data.tags
        self._model = m
        self.info = {
            "model": "LightGBM (gradient-boosted trees), Platt-calibrated, five bands",
            "approved": "V2-52 (5 Nov 2026)",
            "frozen_run": frozen["run"].info.run_id,
            "commit": frozen["commit"][:7],
            "data_hash": frozen["data_hash"],
            "export_date": frozen["export_date"],
            "trained_through": m.trained_through,
            "cutoff": str(m.calibrator.cutoff.date()),
            "features": len(m.features),
            "frozen_tag": tags.get("frozen", ""),
        }
        path = self.p.root / "docs" / "report" / "model_card.json"
        self.card = json.loads(path.read_text(encoding="utf-8"))["dilution"]

    def refresh(self, con) -> None:
        """Score again when a new serving copy has been published."""
        version = os.stat(self.p.serving_db).st_mtime_ns
        if version == self._version:
            return
        with self._lock:
            if version == self._version:
                return
            if self._model is None:
                self._load()
            rows = con.execute("select * from app.company_card").df()
            rows["as_of"] = pd.to_datetime(rows["as_of"])
            newest = rows["as_of"].max()
            current = rows[rows["as_of"] >= newest - pd.Timedelta(days=CURRENT_DAYS)]
            pred = dilution.predict(self._model, current)
            ok = pred["eligible"].to_numpy()
            sub = current[ok].astype({c: float for c in self._model.features})
            boost = self._model.trees.estimator
            contrib = boost.model_.booster_.predict(
                sub[self._model.trees.features], pred_contrib=True, num_iteration=boost.trees_
            )
            names = self._model.trees.features
            by_cik = {}
            for i, (_, row) in enumerate(sub.iterrows()):
                p = pred.loc[row.name]
                factors = [
                    {
                        "feature": f,
                        "label": FEATURES.get(f, (f, "num"))[0],
                        "kind": FEATURES.get(f, (f, "num"))[1],
                        "value": _value(row[f]),
                        "effect": float(contrib[i, j]),
                    }
                    for j, f in enumerate(names)
                ]
                factors.sort(key=lambda x: -abs(x["effect"]))
                by_cik[str(row["cik"])] = {
                    "chance": float(p["dilution_prob"]),
                    "band": int(p["dilution_band"]),
                    "band_name": str(p["dilution_band_name"]),
                    "as_of": row["as_of"].date().isoformat(),
                    "factors": factors,
                }
            self.by_cik = by_cik
            self.as_of = newest.date().isoformat()
            self.current = set(current["cik"].astype(str))
            self._version = version

    def for_company(self, cik: str, card: dict, listed: bool, facts: dict | None = None) -> dict:
        """The forecast, or why there is none (FR-004; the reasons checked by the named cases,
        T019): `facts` as `data.company` gives them (filer type, blank-check, prices, fund)."""
        f = self.by_cik.get(cik)
        if f is not None:
            return {"available": True, **f}
        facts = facts or {}
        if card.get("foreign_filer") or facts.get("filer_type") == "foreign":
            reason = (
                "No forecast for foreign companies: they report their share counts differently "
                "(annual 20-F reports instead of quarterly 10-Q), so the model cannot follow "
                "them (decision V2-27)."
            )
        elif facts.get("is_blank_check"):
            reason = (
                "No forecast for blank-check companies: a shell company without a business of its "
                "own is left out of every question until it merges with one (decision V2-66)."
            )
        elif not listed:
            reason = "No forecast: the company's shares no longer trade."
        elif not facts.get("has_prices", True):
            reason = (
                "No forecast: our data has no share prices for this company, and the model "
                "needs them."
            )
        elif cik not in getattr(self, "current", set()):
            reason = "No forecast: the company's shares have no recent price in our data."
        elif card.get("excluded") or facts.get("is_fund"):
            reason = "No forecast: funds, trusts and similar vehicles are outside this question."
        else:
            reason = (
                "No forecast: the data needed (recent share counts and financial reports) is not "
                "complete for this company."
            )
        return {"available": False, "reason": reason}

    def top(self, n: int = 15) -> list[dict]:
        """The companies with the highest chance today (the landing page)."""
        best = sorted(self.by_cik.items(), key=lambda kv: -kv[1]["chance"])[:n]
        return [{"cik": c, "chance": f["chance"], "band": f["band"]} for c, f in best]
