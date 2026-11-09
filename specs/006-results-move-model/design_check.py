"""006 design check (research.md, 9 Nov) on pseudo-validation years 2016-2018, all before the
first test year (2019).

For each year V: learn from releases whose moves were known before V (from the start year),
score the releases dated in V. Chances are calibrated by Platt per threshold, cross-fitted by
half-year inside V (H1 -> H2 and H2 -> H1), the same for every variant. Measure: mean log loss of
the three chances (V2-41). No test year is read: rows dated 2019 or later are dropped first.

Run: systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run python \
     specs/006-results-move-model/design_check.py   (about 3 minutes)
"""

import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

from sentinel import eda

TH = (0.05, 0.10, 0.20)
TREES = (200, 400, 700, 1000)
TIMING = ["days_since_results", "days_to_next_results", "months_since_report"]

d = eda.load("results_move")
d = d[d["as_of"] < "2019-01-01"]  # nothing from the test years
e = d[d["eligible"].fillna(False) & d["move"].notna()]
e = e.sort_values(["cik", "as_of"], kind="stable").reset_index(drop=True)
F = eda.features(e)
assert "cum_split_after" not in F
e = e.astype({c: float for c in F + ["prev4_mean", "n_prev"]}).copy()
e["sector_code"] = e["sector"].astype("category").cat.codes.astype(float)
z = np.log(np.maximum(e["move"].to_numpy(), 1e-4))
Y = {t: (e["move"] > t).astype(int).to_numpy() for t in TH}


def platt_cross(score, idx, half):
    """Calibrated chances per threshold for rows idx (score = 1-D array over idx)."""
    out = {}
    s = score.reshape(-1, 1)
    for t in TH:
        y = Y[t][idx]
        p = np.empty(len(idx))
        for h in (0, 1):
            fit_m, pred_m = half != h, half == h
            lr = LogisticRegression(C=1e6).fit(s[fit_m], y[fit_m])
            p[pred_m] = lr.predict_proba(s[pred_m])[:, 1]
        out[t] = p
    # monotone: p20 <= p10 <= p5
    out[0.10] = np.minimum(out[0.10], out[0.05])
    out[0.20] = np.minimum(out[0.20], out[0.10])
    return out


def mean_ll(ch, idx):
    return np.mean([log_loss(Y[t][idx], np.clip(ch[t], 1e-6, 1 - 1e-6)) for t in TH])


def lgb_params(objective, seed=0):
    return dict(
        objective=objective,
        learning_rate=0.05,
        n_estimators=max(TREES),
        num_leaves=31,
        min_child_samples=200,
        colsample_bytree=0.8,
        subsample=0.8,
        subsample_freq=1,
        deterministic=True,
        force_row_wise=True,
        n_jobs=8,
        random_state=seed,
        verbose=-1,
    )


rows = []
for V in (2016, 2017, 2018):
    v0, v1 = pd.Timestamp(V, 1, 1), pd.Timestamp(V + 1, 1, 1)
    valid = ((e["as_of"] >= v0) & (e["close_after"] < v1)).to_numpy()
    idx = np.flatnonzero(valid)
    half = (e.loc[valid, "as_of"].dt.month > 6).astype(int).to_numpy()
    res = {"year": V, "valid_rows": len(idx)}
    # base rates from rows known before V
    known = (e["close_after"] < v0).to_numpy()
    res["base_rate"] = mean_ll({t: np.full(len(idx), Y[t][known].mean()) for t in TH}, idx)
    # prev4 baseline: Platt on log prev4_mean; first releases get the base rate
    has = e["n_prev"].to_numpy()[idx] > 0
    lp = np.log(np.maximum(e["prev4_mean"].to_numpy()[idx], 1e-4))
    ch = {t: np.full(len(idx), Y[t][known].mean()) for t in TH}
    sub = platt_cross(lp[has], idx[has], half[has])
    for t in TH:
        ch[t][has] = sub[t]
    res["prev4"] = mean_ll(ch, idx)

    variants = {
        "size_2010": (F + ["prev4_mean", "n_prev"], pd.Timestamp(2010, 1, 1)),
        "size_2012": (F + ["prev4_mean", "n_prev"], pd.Timestamp(2012, 1, 1)),
        "size_no_timing": (
            [c for c in F if c not in TIMING] + ["prev4_mean", "n_prev"],
            pd.Timestamp(2010, 1, 1),
        ),
        "size_sector": (F + ["prev4_mean", "n_prev", "sector_code"], pd.Timestamp(2010, 1, 1)),
    }
    for name, (cols, start) in variants.items():
        t0 = time.time()
        inner = ((e["close_after"] < v0) & (e["as_of"] >= start)).to_numpy()
        m = lgb.LGBMRegressor(**lgb_params("regression"))
        kw = {"categorical_feature": ["sector_code"]} if "sector_code" in cols else {}
        m.fit(e.loc[inner, cols], z[inner], **kw)
        best = min(
            (
                mean_ll(
                    platt_cross(m.predict(e.loc[valid, cols], num_iteration=k), idx, half), idx
                ),
                k,
            )
            for k in TREES
        )
        res[name] = best[0]
        res[name + "_trees"] = best[1]
        if name == "size_2010":
            imp = pd.Series(m.booster_.feature_importance("gain"), index=cols)
            share = imp / imp.sum()
            res["timing_gain_share"] = float(share[TIMING].sum())
            res["top5"] = ", ".join(share.sort_values(ascending=False).index[:5])
        print(V, name, round(best[0], 5), best[1], f"{time.time() - t0:.0f}s", flush=True)
    # direct: three yes/no models, each Platt-calibrated on its own log-odds
    t0 = time.time()
    cols = F + ["prev4_mean", "n_prev"]
    inner = (e["close_after"] < v0).to_numpy()
    raw = {}
    for t in TH:
        c = lgb.LGBMClassifier(**lgb_params("binary")).fit(e.loc[inner, cols], Y[t][inner])
        raw[t] = {k: c.predict_proba(e.loc[valid, cols], num_iteration=k)[:, 1] for k in TREES}
    best = None
    for k in TREES:
        ch = {}
        for t in TH:
            p = np.clip(raw[t][k], 1e-6, 1 - 1e-6)
            ch[t] = platt_cross(np.log(p / (1 - p)), idx, half)[t]
        ch[0.10] = np.minimum(ch[0.10], ch[0.05])
        ch[0.20] = np.minimum(ch[0.20], ch[0.10])
        ll = mean_ll(ch, idx)
        best = min(best, (ll, k)) if best else (ll, k)
    res["direct"], res["direct_trees"] = best
    print(V, "direct", round(best[0], 5), best[1], f"{time.time() - t0:.0f}s", flush=True)
    rows.append(res)

out = pd.DataFrame(rows).set_index("year")
pd.set_option("display.width", 250)
print(out.round(5).T)
cols = ["base_rate", "prev4", "size_2010", "size_2012", "size_no_timing", "size_sector", "direct"]
print("\nmean over 2016-2018:")
print(out[cols].mean().round(5))
print("\ndifferences from size_2010 per year (negative = better):")
print(out[cols].sub(out["size_2010"], axis=0).round(5))
