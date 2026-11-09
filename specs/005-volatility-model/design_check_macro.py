"""005 design check, part 3 (9 Nov, run after the first full run of the notebook): LightGBM on
the change from past volatility, with and without the macro family, on 2016-2018. No row dated 2019
or later is read.

Run: systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run python \
     specs/005-volatility-model/design_check_macro.py   (about 3 minutes)
"""

import lightgbm as lgb
import numpy as np
import pandas as pd

from sentinel import eda

TREES = (100, 200, 400, 700, 1000)
d = eda.load("volatility")
d = d[d["as_of"] < "2019-01-01"]
e = d[d["eligible_volatility"].fillna(False) & (d["vol_63_future"] > 0)]
e = e.sort_values(["cik", "as_of"], kind="stable").reset_index(drop=True)
F = [c for c in eda.features(e) if c not in ("cum_split_after", "sector")]
MACRO = [c for c in F if eda.family(c) == "macro"]
e = e.astype({c: float for c in F}).copy()
z = np.log(e["vol_63_future"].to_numpy())
past = np.log(np.maximum(e["vol_63"].to_numpy(), 1e-4))
params = dict(
    objective="regression",
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
    random_state=0,
    verbose=-1,
)
out = {}
for V in (2016, 2017, 2018):
    known = (e["window_end"] < pd.Timestamp(V, 1, 1)).to_numpy()
    year = (e["as_of"].dt.year == V).to_numpy()
    for name, cols in {
        "all features": F,
        "without macro": [c for c in F if c not in MACRO],
    }.items():
        m = lgb.LGBMRegressor(**params).fit(e.loc[known, cols], (z - past)[known])
        out[(V, name)] = min(
            float(
                np.mean(
                    np.abs(m.predict(e.loc[year, cols], num_iteration=k) + past[year] - z[year])
                )
            )
            for k in TREES
        )
        print(V, name, round(out[(V, name)], 4), flush=True)
t = pd.Series(out).unstack()
t["without minus with"] = t["without macro"] - t["all features"]
print(t.round(4))
print(t.mean().round(4))
print(len(MACRO), "macro features:", MACRO)
