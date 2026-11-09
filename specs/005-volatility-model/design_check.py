"""005 design check (research.md, 9 Nov) on years before the first test year (2019): no row dated
2019 or later is read.

For each year V in 2014-2018, LightGBM learns from the rows whose answers were known before V and
forecasts the log volatility of the rows dated in V (out of sample). Part 1 compares, on 2016-2018,
what the trees learn (the log of future volatility, or its change from past volatility) and their
loss (squared or absolute error), by the mean absolute error of the log (V2-56), with the naive
baseline and the mean-reversion rule beside them. Part 2 sets an 80% range for 2016-2018 from
earlier years' out-of-sample errors (V2-10): pooled over all earlier years, only the year before,
or (as Gemini did) the training rows' own errors; and measures how often it holds.

Run: systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run python \
     specs/005-volatility-model/design_check.py   (about 10 minutes)
"""

import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from sentinel import eda

TREES = (100, 200, 400, 700, 1000)
YEARS = (2014, 2015, 2016, 2017, 2018)

d = eda.load("volatility")
d = d[d["as_of"] < "2019-01-01"]  # nothing from the test years
e = d[d["eligible_volatility"].fillna(False) & (d["vol_63_future"] > 0)]
e = e.sort_values(["cik", "as_of"], kind="stable").reset_index(drop=True)
F = [c for c in eda.features(e) if c not in ("cum_split_after", "sector")]
e = e.astype({c: float for c in F}).copy()
z = np.log(e["vol_63_future"].to_numpy())
past = np.log(np.maximum(e["vol_63"].to_numpy(), 1e-4))
print(f"{len(e):,} rows before 2019, {len(F)} features", flush=True)


def params(objective, seed=0):
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


def mae(a, b):
    return float(np.mean(np.abs(a - b)))


rows, oos, insample = [], {}, {}
for V in YEARS:
    known = (e["window_end"] < pd.Timestamp(V, 1, 1)).to_numpy()
    year = (e["as_of"].dt.year == V).to_numpy()
    res = {"year": V, "train_rows": int(known.sum()), "rows": int(year.sum())}
    res["baseline"] = mae(past[year], z[year])
    rule = LinearRegression().fit(past[known].reshape(-1, 1), z[known])
    res["rule"] = mae(rule.predict(past[year].reshape(-1, 1)), z[year])
    res["rule_slope"] = float(rule.coef_[0])
    variants = {
        "level_l2": ("regression", False),
        "level_l1": ("l1", False),
        "change_l2": ("regression", True),
        "change_l1": ("l1", True),
    }
    if V < 2016:  # only the range check needs these years: one variant
        variants = {"level_l1": variants["level_l1"]}
    for name, (objective, change) in variants.items():
        t0 = time.time()
        target = z - past if change else z
        m = lgb.LGBMRegressor(**params(objective)).fit(e.loc[known, F], target[known])
        best = None
        for k in TREES:
            f = m.predict(e.loc[year, F], num_iteration=k) + (past[year] if change else 0)
            best = min(best, (mae(f, z[year]), k)) if best else (mae(f, z[year]), k)
        res[name], res[name + "_trees"] = best
        if name == "level_l1":
            oos[V] = m.predict(e.loc[year, F], num_iteration=400) - z[year]  # errors, 400 trees
            insample[V] = m.predict(e.loc[known, F], num_iteration=400) - z[known]
        print(V, name, round(best[0], 4), best[1], f"{time.time() - t0:.0f}s", flush=True)
    rows.append(res)

out = pd.DataFrame(rows).set_index("year")
pd.set_option("display.width", 250)
print(out.round(4).T)
main = out.loc[2016:2018, ["baseline", "rule", "level_l2", "level_l1", "change_l2", "change_l1"]]
print("\nmean absolute error of the log, 2016-2018 (lower is better):")
print(main.round(4))
print(main.mean().round(4))

# Part 2: the 80% range, set on earlier years' errors, held on 2016-2018 (level_l1, 400 trees)
cover = {}
for V in (2016, 2017, 2018):
    err = oos[V]  # forecast minus answer, in logs
    ways = {
        "all earlier years": np.concatenate([oos[t] for t in YEARS if t < V]),
        "the year before": oos[V - 1],
        "training rows' own errors": insample[V],
    }
    for way, ref in ways.items():
        lo, hi = np.quantile(ref, [0.10, 0.90])  # answer = forecast - error
        inside = (err >= lo) & (err <= hi)
        cover[(V, way)] = round(float(inside.mean()), 3)
print("\nshare of answers inside the 80% range:")
print(pd.Series(cover).unstack())
