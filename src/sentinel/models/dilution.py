"""The dilution model (feature 007), approved by the researcher on 5 November 2026 (V2-52): LightGBM
made for a target year exactly as for each walk-forward test year of
`notebooks/007-dilution-model.ipynb`, which imports this module.

For target year Y (2023 for the frozen model, the holdout's first year): the trees learn from the
rows whose answers were known before Y-1 (the inner block of `eda.folds`); the settings and the
number of trees are chosen by predicting the rows dated in Y-1 whose answers were known before Y
(the validation block), and on those rows the chances are calibrated (Platt) and the five band
edges set. Every step is a `Dated` (V2-49): the trees learn no answer known from Y-1 on, the
calibration and the bands none from Y on, and none of them scores a row dated before its cutoff.
The split-like "yes" answers are dropped first (V2-39, V2-40); the trees leave out
`cum_split_after` (look-ahead, V2-38) and the insider and macro families (V2-36).
"""

import hashlib
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

from sentinel import eda, validation
from sentinel.models.dated import Dated

ANSWER, ELIGIBILITY = "dilution", "eligible_dilution"
SEED, THREADS = 0, 8
LOOK_AHEAD = ["cum_split_after"]  # the split ratios after the row's day (V2-38)
LEFT_OUT = ("insider", "macro")  # families the trees leave out (V2-36)
GRID = [{"num_leaves": n, "min_child_samples": m} for n in (15, 63) for m in (100, 500)]
TREES = [100, 150, 200, 300, 400, 500, 600, 800, 1000, 1250, 1500, 2000]
TARGET_YEAR = eda.DEV_END.year + 1
BAND_NAMES = {1: "1 · Very low risk", 2: "2 · Low risk", 3: "3 · Moderate risk",
              4: "4 · High risk", 5: "5 · Very high risk"}  # fmt: skip


def features(rows: pd.DataFrame) -> list[str]:
    """The trees' inputs: the export's features without the look-ahead column and without the
    insider and macro families."""
    return [c for c in eda.features(rows)
            if c not in LOOK_AHEAD and eda.family(c) not in LEFT_OUT]  # fmt: skip


def split_like_answers(
    con: duckdb.DuckDBPyConnection, rows: pd.DataFrame | None = None
) -> pd.DataFrame:
    """`cik`, `as_of` of the "yes" answers that are a stock split read as dilution (V2-39); `rows`
    (cik, as_of, window_end of answers of 1): the answers to check instead of the development
    label table (the holdout test's 2023+ answers, 010)."""
    t = validation.split_dilution(con, rows)
    if t.empty:
        return pd.DataFrame({"cik": pd.Series(dtype=str),
                             "as_of": pd.Series(dtype="datetime64[ns]")})  # fmt: skip
    t = t[t["split_read_as_dilution"]]
    as_of = pd.to_datetime(t["as_of"]).astype("datetime64[ns]")
    return pd.DataFrame({"cik": t["cik"].astype(str).to_numpy(), "as_of": as_of.to_numpy()})


def learnable(raw: pd.DataFrame, split_like: pd.DataFrame) -> pd.DataFrame:
    """The rows to learn from: this question's flag, an answer, not a split-like answer; sorted by
    company and date, the features as floats."""
    keep = raw[ELIGIBILITY] & raw[ANSWER].notna()
    split = pd.MultiIndex.from_frame(split_like[["cik", "as_of"]])
    keep &= ~pd.MultiIndex.from_arrays([raw["cik"], raw["as_of"]]).isin(split)
    rows = raw[keep].sort_values(["cik", "as_of"], kind="stable").reset_index(drop=True)
    return rows.astype({c: float for c in eda.features(rows)}).copy()


def _logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


class Boost(BaseEstimator, ClassifierMixin):
    """LightGBM that forecasts with its first `trees_` trees: the number of trees is a setting
    chosen by predicting the validation year, not by early stopping inside the fit (V2-49)."""

    def __init__(self, params=None, n_estimators=TREES[-1], seed=SEED):
        self.params, self.n_estimators, self.seed = params, n_estimators, seed

    def fit(self, X, y):
        self.model_ = lgb.LGBMClassifier(
            objective="binary", learning_rate=0.05, n_estimators=self.n_estimators,
            colsample_bytree=0.8, subsample=0.8, subsample_freq=1, deterministic=True,
            force_row_wise=True, n_jobs=THREADS, random_state=self.seed, verbose=-1,
            **(self.params or {})).fit(X, y)  # fmt: skip
        self.trees_ = self.n_estimators
        return self

    def predict_proba(self, X):
        return self.model_.predict_proba(X, num_iteration=self.trees_)


class Bands(BaseEstimator):
    """Five bands by chance: edges at the quintiles of the chances it is fitted on."""

    def fit(self, X, y=None):
        self.edges_ = np.quantile(np.asarray(X, dtype=float)[:, 0], [0.2, 0.4, 0.6, 0.8])
        return self

    def predict(self, X):
        return np.searchsorted(self.edges_, np.asarray(X, dtype=float)[:, 0], side="right") + 1


@dataclass
class DilutionModel:
    """The model for one target year: the trees, the calibration and the band edges, each a
    `Dated` with its cutoff."""

    features: list[str]
    trees: Dated
    calibrator: Dated
    bands: Dated
    setting: dict
    seed: int
    year: int
    trained_through: str
    provenance: dict = field(default_factory=dict)
    tried: dict = field(default_factory=dict, repr=False)  # validation log loss per setting
    valid_raw: np.ndarray | None = field(default=None, repr=False)  # trees' validation chances
    question: str = ANSWER
    level: str = "lightgbm"
    eligibility_col: str = ELIGIBILITY

    def chances(self, rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """The trees' chances and the calibrated chances of `rows`."""
        raw = self.trees.predict(rows)
        return raw, self.calibrator.predict(rows[["as_of"]].assign(logit=_logit(raw)))


def fit(rows: pd.DataFrame, year: int = TARGET_YEAR, cols: list[str] | None = None,
        seed: int = SEED, setting: dict | None = None,
        provenance: dict | None = None) -> DilutionModel:  # fmt: skip
    """The model for target `year` from learnable `rows` (see the module's docstring). With
    `setting` (`params`, `trees`) only that setting is fitted, as the hypothesis checks do."""
    fold = eda.folds(rows, ANSWER, [year])[year]
    inner, valid = rows[fold["inner"]], rows[fold["valid"]]
    cols = cols or features(rows)
    y_valid = valid[ANSWER].astype(int)
    model_cutoff, cutoff = pd.Timestamp(year - 1, 1, 1), pd.Timestamp(year, 1, 1)
    tried, fitted = {}, {}
    for params in [setting["params"]] if setting else GRID:
        n = setting["trees"] if setting else TREES[-1]
        trees = Dated(Boost(params, n, seed), ANSWER, cols).fit(inner, model_cutoff)
        fitted[str(params)] = trees
        for k in [n] if setting else TREES:
            trees.estimator.trees_ = k
            tried[(str(params), k)] = log_loss(y_valid, trees.predict(valid))
    best_params, best_trees = min(tried, key=tried.get)
    trees = fitted[best_params]
    trees.estimator.trees_ = best_trees
    p_valid = trees.predict(valid)
    frame = valid[["as_of", "window_end"]]
    calibrator = Dated(LogisticRegression(C=1e6), ANSWER, ["logit"])
    calibrator.fit(frame.assign(logit=_logit(p_valid)), cutoff, y=y_valid)
    assert calibrator.estimator.coef_[0, 0] > 0  # it keeps the chances' order: bands use the trees'
    bands = Dated(Bands(), ANSWER, ["chance"]).fit(frame.assign(chance=p_valid), cutoff, y=y_valid)
    return DilutionModel(list(cols), trees, calibrator, bands,
                         {"params": trees.estimator.params, "trees": best_trees}, seed, year,
                         str(inner["window_end"].max().date()), provenance or {}, tried,
                         p_valid)  # fmt: skip


def predict(model: DilutionModel, rows: pd.DataFrame) -> pd.DataFrame:
    """One row per row of `rows` (same index): whether it is eligible, and for eligible rows the
    calibrated chance and the band (1-5) with its name. Every step refuses a row dated before its
    cutoff."""
    out = pd.DataFrame({
        "cik": rows["cik"].astype(str), "as_of": pd.to_datetime(rows["as_of"]),
        "eligible": rows[model.eligibility_col].fillna(False).astype(bool),
        "dilution_prob": np.nan,
        "dilution_band": pd.Series(pd.NA, index=rows.index, dtype="Int64"),
        "dilution_band_name": pd.Series(pd.NA, index=rows.index, dtype="string"),
    }, index=rows.index)  # fmt: skip
    mask = out["eligible"].to_numpy()
    if not mask.any():
        return out
    sub = rows.loc[mask].assign(as_of=out.loc[mask, "as_of"])
    sub = sub.astype({c: float for c in model.features})
    raw, chance = model.chances(sub)
    band = model.bands.predict(sub[["as_of"]].assign(chance=raw))
    out.loc[mask, "dilution_prob"] = chance
    out.loc[mask, "dilution_band"] = band
    out.loc[mask, "dilution_band_name"] = [BAND_NAMES[int(b)] for b in band]
    return out


def provenance(export: Path) -> dict:
    """What a saved model was made from: the git commit, the export's date and its data hash."""
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return {"git_commit": commit.stdout.strip(),
            "export_date": date.fromtimestamp(export.stat().st_mtime).isoformat(),
            "data_hash": hashlib.sha256(export.read_bytes()).hexdigest()[:12]}  # fmt: skip


def save(model: DilutionModel, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, p)


def load(path: Path | str) -> DilutionModel:
    return joblib.load(path)
