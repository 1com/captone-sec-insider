"""Pilot model: logistic regression and LightGBM against a market-only baseline (research R6).

Train on 2006–2010 pilot events whose 63-session window ends before 2011 (purged); test on 2011.
The selected model (lower 2011 log loss) is refitted on all pilot events to score recent events,
which never receive an outcome (constitution, Prototype Exception).
"""

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from mvp.pipeline.features import ALL_FEATURES, MARKET_FEATURES


def _make(kind: str, mp: dict):
    if kind == "logit":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            LogisticRegression(C=mp["logit_c"], max_iter=5000),
        )
    return LGBMClassifier(**mp["lgbm"], random_state=mp["seed"], verbose=-1)


def _metrics(y, p, net) -> dict:
    top = p >= np.quantile(p, 0.8)
    return {
        "n": int(len(y)),
        "base_rate": float(np.mean(y)),
        "auc": float(roc_auc_score(y, p)) if len(set(y)) > 1 else None,
        "log_loss": float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
        "top_fifth_net": float(np.mean(net[top])),
        "all_net": float(np.mean(net)),
        "top_fifth_hit": float(np.mean(y[top])),
    }


def _calibration(y, p, bins: int) -> list[dict]:
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    which = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    return [
        {
            "pred": float(p[which == b].mean()),
            "obs": float(y[which == b].mean()),
            "n": int((which == b).sum()),
        }
        for b in range(len(edges) - 1)
        if (which == b).any()
    ]


def _weights(model, kind: str, cols: list[str]) -> dict[str, float]:
    """Logistic: coefficient per standardised input (sign = direction). LightGBM: share of
    total split gain (always >= 0)."""
    if kind == "logit":
        coef = model.named_steps["logisticregression"].coef_[0][: len(cols)]
        return {c: float(w) for c, w in zip(cols, coef, strict=True)}
    gain = model.booster_.feature_importance(importance_type="gain").astype(float)
    total = gain.sum() or 1.0
    return {c: float(g / total) for c, g in zip(cols, gain, strict=True)}


def _learned(fitted, base, final, selected, feats, market) -> dict:
    return {
        "logit": _weights(fitted["logit"], "logit", feats),
        "lgbm": _weights(fitted["lgbm"], "lgbm", feats),
        "baseline": _weights(base, selected, market),
        "final": _weights(final, selected, feats),
        "baseline_kind": selected,
        "final_kind": selected,
    }


def run(data: pd.DataFrame, recent: pd.DataFrame, settings) -> dict:
    """`data`: pilot events with features, `net_63_iwm` and `window_end`; returns results."""
    mp = settings.mvp["model"]
    h = settings.primary_horizon
    data = data.dropna(subset=[f"net_{h}_iwm"]).copy()
    data["y"] = (data[f"net_{h}_iwm"] > 0).astype(int)
    year = pd.to_datetime(data["signal_date"]).dt.year
    test_start = pd.Timestamp(f"{mp['test_year']}-01-01")
    train = data[
        (year <= mp["train_last_year"]) & (pd.to_datetime(data["window_end"]) < test_start)
    ]
    test = data[year == mp["test_year"]]
    feats, market = list(ALL_FEATURES), list(MARKET_FEATURES)

    results, fitted = {}, {}
    for kind in ("logit", "lgbm"):
        model = _make(kind, mp).fit(train[feats], train["y"])
        p = model.predict_proba(test[feats])[:, 1]
        results[kind] = _metrics(test["y"].to_numpy(), p, test[f"net_{h}_iwm"].to_numpy())
        results[kind]["calibration"] = _calibration(test["y"].to_numpy(), p, mp["calibration_bins"])
        fitted[kind] = model
    selected = min(("logit", "lgbm"), key=lambda k: results[k]["log_loss"])
    base = _make(selected, mp).fit(train[market], train["y"])
    pb = base.predict_proba(test[market])[:, 1]
    results["baseline"] = _metrics(test["y"].to_numpy(), pb, test[f"net_{h}_iwm"].to_numpy())
    results["baseline"]["calibration"] = _calibration(
        test["y"].to_numpy(), pb, mp["calibration_bins"]
    )

    # No-skill reference: predict the training base rate for every test event.
    const = np.full(len(test), float(train["y"].mean()))
    results["constant"] = _metrics(test["y"].to_numpy(), const, test[f"net_{h}_iwm"].to_numpy())
    results["constant"]["auc"] = 0.5
    results["constant"]["top_fifth_net"] = None
    results["constant"]["top_fifth_hit"] = None

    imp = permutation_importance(
        fitted[selected],
        test[feats],
        test["y"],
        scoring="neg_log_loss",
        n_repeats=mp["importance_repeats"],
        random_state=mp["seed"],
    )
    drivers = sorted(
        (
            {
                "feature": f,
                "label": ALL_FEATURES[f],
                "importance": float(imp.importances_mean[i]),
                "std": float(imp.importances_std[i]),
            }
            for i, f in enumerate(feats)
        ),
        key=lambda d: d["importance"],
        reverse=True,
    )

    # Direction of each driver for plain-language reading: the logistic sign on standardised
    # features (computed on the training data) says whether more of it raises the score.
    logit = fitted["logit"].named_steps["logisticregression"]
    signs = dict(zip(feats, np.sign(logit.coef_[0][: len(feats)]), strict=True))
    for d in drivers:
        d["direction"] = "raises" if signs.get(d["feature"], 0) > 0 else "lowers"

    final = _make(selected, mp).fit(data[feats], data["y"])
    pilot_scores = final.predict_proba(data[feats])[:, 1]
    learned = _learned(fitted, base, final, selected, feats, market)
    scores = recent[["event_id"]].copy()
    if len(recent):
        scores["score"] = final.predict_proba(recent[feats])[:, 1]
        scores["percentile"] = [float((pilot_scores <= s).mean()) for s in scores["score"]]
        scores["partial"] = recent[feats].isna().sum(axis=1).to_numpy() >= 4
    return {
        "selected": selected,
        "results": results,
        "drivers": drivers[:10],
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "n_all": int(len(data)),
        "train_years": [int(year.min()), int(mp["train_last_year"])],
        "test_year": int(mp["test_year"]),
        "base_rate_all": float(data["y"].mean()),
        "learned": learned,
        "score_quantiles": {
            q: float(np.quantile(pilot_scores, q / 100)) for q in (5, 25, 50, 75, 95)
        },
        "scores": scores,
    }
