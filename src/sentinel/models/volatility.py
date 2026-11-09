"""The volatility model (feature 005), approved by the researcher on 9 November 2026 (V2-58):
LightGBM made for a target year exactly as for each walk-forward test year of
`notebooks/005-volatility-model.ipynb`, which imports this module.

The trees forecast the change from past volatility, log(next 63 sessions' volatility) −
log(`vol_63`), and add it to log(`vol_63`) (`specs/005-volatility-model/research.md`, R3). For
target year Y (2023 for the frozen model, the holdout's first year): the trees learn from the rows
whose answers were known before Y-1 (the inner block of `eda.folds`); the setting and the number of
trees are chosen by the mean absolute log error (V2-56) of the rows dated in Y-1 whose answers were
known before Y. Around each forecast, **the 80% range** is set on the out-of-sample errors of every
earlier year from 2014 (V2-10): each earlier year forecast by the model of its own walk-forward
year, which learned only from the years before it; the five band edges are the quintiles of the
same forecasts. Every step is a `Dated` (V2-49): the trees learn no answer known from Y-1 on, the
range and the bands none from Y on, and none scores a row dated before its cutoff.

Inputs: the export's features without the macro family (V2-57, decided after the first full run),
`cum_split_after` (look-ahead) or `sector` (the current SIC, not point-in-time).
"""

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin

from sentinel import eda
from sentinel.models.dated import Dated
from sentinel.models.dilution import BAND_NAMES, Bands

QUESTION, ANSWER, ELIGIBILITY = "volatility", "vol_63_future", "eligible_volatility"
KNOWN = eda.WINDOW_END[QUESTION]  # the day a row's answer is known: the end of its 63 sessions
SEED, THREADS = 0, 8
FLOOR = 1e-4  # the log of past volatility uses at least this (a price that never moved)
FIRST_YEAR = 2014  # the out-of-sample history behind the range starts here (V2-10, research R4)
NOT_INPUTS = ["cum_split_after", "sector"]  # look-ahead; the current SIC, not point-in-time
LEFT_OUT = ("macro",)  # V2-57
GRID = [{"num_leaves": n, "min_child_samples": m} for n in (15, 63) for m in (100, 500)]
TREES = [50, 100, 150, 200, 300, 400, 600, 800, 1000]
TARGET_YEAR = eda.DEV_END.year + 1
OUTPUT = ["vol_forecast", "vol_low_80", "vol_high_80"]


def all_features(rows: pd.DataFrame) -> list[str]:
    """Every feature column of the export, the macro family included (the notebook's checks)."""
    return [c for c in eda.features(rows) if c not in NOT_INPUTS]


def features(rows: pd.DataFrame) -> list[str]:
    """The model's inputs: the export's features without the macro family (V2-57)."""
    return [c for c in all_features(rows) if eda.family(c) not in LEFT_OUT]


def learnable(raw: pd.DataFrame) -> pd.DataFrame:
    """The rows to learn from: this question's flag and an answer above 0 (an answer of 0 has no
    logarithm); sorted by company and date, the features as floats."""
    keep = raw[ELIGIBILITY].fillna(False).astype(bool) & (raw[ANSWER] > 0)
    rows = raw[keep].sort_values(["cik", "as_of"], kind="stable").reset_index(drop=True)
    return rows.astype({c: float for c in all_features(rows)})


def log_vol(rows: pd.DataFrame) -> pd.Series:
    """The log of each row's answer."""
    return np.log(rows[ANSWER].astype(float))


def past_of(X: pd.DataFrame) -> np.ndarray:
    """log(`vol_63`): the naive baseline, and the starting point of the change models."""
    return np.log(np.maximum(X["vol_63"].to_numpy(dtype=float), FLOOR))


def with_past(cols) -> list[str]:
    """The columns a change model reads: its inputs and `vol_63` for its starting point."""
    return list(cols) + ([] if "vol_63" in cols else ["vol_63"])


class Change(BaseEstimator, RegressorMixin):
    """A model of the change from past volatility: it learns log(future) − log(past) on `cols` and
    forecasts log(past) + the change, so it starts from the naive baseline whatever its inputs."""

    def __init__(self, base, cols):
        self.base, self.cols = base, cols

    def fit(self, X, y):
        self.base.fit(X[self.cols], np.asarray(y, dtype=float) - past_of(X))
        return self

    def predict(self, X):
        return past_of(X) + self.base.predict(X[self.cols])


class Boost(BaseEstimator, RegressorMixin):
    """LightGBM forecasting with its first `trees_` trees: the number of trees is a setting chosen
    by predicting the validation year, never by early stopping inside the fit (V2-49)."""

    def __init__(self, params=None, n_estimators=TREES[-1], seed=SEED):
        self.params, self.n_estimators, self.seed = params, n_estimators, seed

    def fit(self, X, y):
        self.model_ = lgb.LGBMRegressor(
            objective="regression", learning_rate=0.05, n_estimators=self.n_estimators,
            colsample_bytree=0.8, subsample=0.8, subsample_freq=1, deterministic=True,
            force_row_wise=True, n_jobs=THREADS, random_state=self.seed, verbose=-1,
            **(self.params or {})).fit(X, y)  # fmt: skip
        self.trees_ = self.n_estimators
        return self

    def predict(self, X):
        return self.model_.predict(X, num_iteration=self.trees_)


class Range(BaseEstimator):
    """The 80% range (V2-10): the 10th and 90th percentiles of earlier years' out-of-sample errors
    (forecast minus answer, in logs). Around a forecast f the answer lies between f − q90 and
    f − q10 eight times in ten, if the future errs like the past."""

    def fit(self, X, y):
        self.q10_, self.q90_ = (float(v) for v in np.quantile(np.asarray(y, float), [0.1, 0.9]))
        return self

    def predict(self, X):
        f = np.asarray(X, dtype=float)[:, 0]
        return np.column_stack([f - self.q90_, f - self.q10_])


def fit_forecast(rows: pd.DataFrame, year: int, cols: list[str] | None = None, seed: int = SEED,
                 setting: dict | None = None) -> dict:  # fmt: skip
    """The trees for walk-forward year `year`: they learn from the inner rows; the setting and the
    number of trees are chosen by the mean absolute log error of the validation year (one fit of
    the most trees per setting). With `setting` (`params`, `trees`) only that one is fitted, as the
    hypothesis checks do. Returns the `Dated` forecast with its setting and the losses tried."""
    fold = eda.folds(rows, QUESTION, [year])[year]
    inner, valid = rows[fold["inner"]], rows[fold["valid"]]
    cols = list(cols or features(rows))
    target, truth = log_vol(inner), log_vol(valid).to_numpy()
    tried, fitted = {}, {}
    for params in [setting["params"]] if setting else GRID:
        n = setting["trees"] if setting else max(TREES)
        model = Dated(Change(Boost(params, n, seed), cols), QUESTION, with_past(cols))
        model.fit(inner, pd.Timestamp(year - 1, 1, 1), y=target)
        fitted[str(params)] = model
        for k in [n] if setting else TREES:
            model.estimator.base.trees_ = k
            tried[(str(params), k)] = float(np.mean(np.abs(model.predict(valid) - truth)))
    key, trees = min(tried, key=tried.get)
    model = fitted[key]
    model.estimator.base.trees_ = trees
    params = model.estimator.base.params
    return {"model": model, "params": {**params, "trees": trees},
            "setting": {"params": params, "trees": trees},
            "tried": {f"{p} {t}": round(v, 5) for (p, t), v in tried.items()}}  # fmt: skip


def history(rows: pd.DataFrame, year: int, first: int | None = None, echo=None) -> pd.DataFrame:
    """The out-of-sample forecasts and errors of every year from `first` (default `FIRST_YEAR`) to
    `year` - 1, each from the trees of its own walk-forward year (`fit_forecast`)."""
    out = []
    for t in range(FIRST_YEAR if first is None else first, year):
        test = rows[eda.folds(rows, QUESTION, [t])[t]["test"]]
        forecast = fit_forecast(rows, t)["model"].predict(test)
        out.append(pd.DataFrame({"as_of": test["as_of"], KNOWN: test[KNOWN], "forecast": forecast,
                                 "error": forecast - log_vol(test).to_numpy(), "year": t},
                                index=test.index))  # fmt: skip
        if echo:
            echo(f"  volatility: out-of-sample history {t} ({len(test):,} rows)")
    return pd.concat(out)


@dataclass
class VolatilityModel:
    """The model for one target year: the trees' forecast, the 80% range and the band edges, each
    a `Dated` with its cutoff."""

    features: list[str]
    forecast: Dated
    range: Dated
    bands: Dated
    setting: dict
    seed: int
    year: int
    trained_through: str
    history_years: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    tried: dict = field(default_factory=dict, repr=False)  # validation loss per setting and trees
    question: str = QUESTION
    level: str = "lightgbm"
    eligibility_col: str = ELIGIBILITY


def fit(rows: pd.DataFrame, year: int = TARGET_YEAR, provenance: dict | None = None,
        past: pd.DataFrame | None = None, echo=None) -> VolatilityModel:  # fmt: skip
    """The model for target `year` from learnable `rows` (see the module's docstring). `past`: the
    out-of-sample history of earlier years if already computed (the notebook's walk-forward);
    otherwise it is computed here, which takes minutes."""
    fit_ = fit_forecast(rows, year)
    past = history(rows, year, echo=echo) if past is None else past
    cutoff = pd.Timestamp(year, 1, 1)
    hist = past[(past["year"] < year) & (past[KNOWN] < cutoff)]
    rng = Dated(Range(), QUESTION, ["forecast"]).fit(hist, cutoff, y=hist["error"])
    bands = Dated(Bands(), QUESTION, ["forecast"]).fit(hist, cutoff, y=hist["error"])
    inner = eda.folds(rows, QUESTION, [year])[year]["inner"]
    model = fit_["model"]
    return VolatilityModel(list(model.features), model, rng, bands, fit_["setting"], SEED, year,
                           str(rows.loc[inner, KNOWN].max().date()),
                           sorted(int(y) for y in hist["year"].unique()), provenance or {},
                           fit_["tried"])  # fmt: skip


def predict(model: VolatilityModel, rows: pd.DataFrame) -> pd.DataFrame:
    """One row per row of `rows` (same index): whether it is eligible and, for eligible rows, the
    expected volatility (`vol_forecast`), its 80% range (`vol_low_80`, `vol_high_80`) and the band
    (1-5) with its name. Every step refuses a row dated before its cutoff; a missing column is an
    error."""
    needed = ["cik", "as_of", model.eligibility_col, *model.features]
    missing = [c for c in needed if c not in rows.columns]
    if missing:
        raise KeyError(f"missing columns: {missing}")
    out = pd.DataFrame({
        "cik": rows["cik"].astype(str), "as_of": pd.to_datetime(rows["as_of"]),
        "eligible": rows[model.eligibility_col].fillna(False).astype(bool),
        **{c: np.nan for c in OUTPUT},
        "vol_band": pd.Series(pd.NA, index=rows.index, dtype="Int64"),
        "vol_band_name": pd.Series(pd.NA, index=rows.index, dtype="string"),
    }, index=rows.index)  # fmt: skip
    mask = out["eligible"].to_numpy()
    if not mask.any():
        return out
    sub = rows.loc[mask].assign(as_of=out.loc[mask, "as_of"])
    sub = sub.astype({c: float for c in model.features})
    frame = sub[["as_of"]].assign(forecast=model.forecast.predict(sub))
    low, high = model.range.predict(frame).T
    band = model.bands.predict(frame)
    out.loc[mask, "vol_forecast"] = np.exp(frame["forecast"].to_numpy())
    out.loc[mask, "vol_low_80"] = np.exp(low)
    out.loc[mask, "vol_high_80"] = np.exp(high)
    out.loc[mask, "vol_band"] = band
    out.loc[mask, "vol_band_name"] = [BAND_NAMES[int(b)] for b in band]
    return out


def save(model: VolatilityModel, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, p)


def load(path: Path | str) -> VolatilityModel:
    return joblib.load(path)
