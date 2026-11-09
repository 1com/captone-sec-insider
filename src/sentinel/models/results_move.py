"""The results-day move model (feature 006), approved by the researcher on 9 November 2026 (V2-55):
LightGBM made for a target year exactly as for each walk-forward test year of
`notebooks/006-results-move-model.ipynb`, which imports this module.

The trees forecast the log of the move's typical size (the move beyond the market from the close
before a results release to the close after its 8-K); three Platt calibrations turn the forecast
into the chances of a move above 5%, 10% and 20% (D62; `specs/006-results-move-model/research.md`,
R3), put in order. For target year Y (2023 for the frozen model, the holdout's first year): the
trees learn from the releases whose moves were known before Y-1 (the inner block of `eda.folds`);
the setting and the number of trees are chosen by predicting the releases dated in Y-1 whose moves
were known before Y (the validation block), by the mean log loss of the three chances calibrated on
that block (V2-41); on those releases the chances are calibrated and the five band edges set,
ordered by the chance above 10% (V2-53). Every step is a `Dated` (V2-49): the trees learn no move
known from Y-1 on, the calibrations and bands none from Y on, and none scores a row dated before its
cutoff.

Inputs: the export's features without the three release-timing features (V2-54), plus the
company's history `prev4_mean` and `n_prev` (declared, spec FR-002). Never `cum_split_after`
(look-ahead) or `sector` (each company's current SIC, not point-in-time).
"""

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

from sentinel import eda
from sentinel.models.dated import Dated
from sentinel.models.dilution import BAND_NAMES, Bands

QUESTION, ANSWER, ELIGIBILITY = "results_move", "move", "eligible"
KNOWN = eda.WINDOW_END[QUESTION]  # the day a release's move is known: the close after its 8-K
SEED, THREADS = 0, 8
EVENTS = (0.05, 0.10, 0.20)  # a move above 5%, 10% and 20% beyond the market (D62)
CHANCES = [f"p_move_{round(e * 100)}" for e in EVENTS]
FLOOR = 1e-4  # the log of a move uses at least 0.01% (a handful of moves are exactly 0)
TIMING = ["days_since_results", "days_to_next_results", "months_since_report"]  # V2-54
HISTORY = ["prev4_mean", "n_prev"]  # the company's earlier moves (declared, spec FR-002)
NOT_INPUTS = ["cum_split_after", "sector"]  # look-ahead; the current SIC, not point-in-time
GRID = [{"num_leaves": n, "min_child_samples": m} for n in (15, 63) for m in (100, 500)]
TREES = [50, 100, 150, 200, 300, 400, 600, 800]
TARGET_YEAR = eda.DEV_END.year + 1


def features(rows: pd.DataFrame) -> list[str]:
    """The inputs: the export's features without the release-timing features, then the history."""
    return [c for c in eda.features(rows) if c not in TIMING + NOT_INPUTS] + HISTORY


def learnable(raw: pd.DataFrame) -> pd.DataFrame:
    """The releases to learn from: this question's flag and a move; sorted by company and date,
    the inputs as floats."""
    keep = raw[ELIGIBILITY].fillna(False).astype(bool) & raw[ANSWER].notna()
    rows = raw[keep].sort_values(["cik", "as_of"], kind="stable").reset_index(drop=True)
    return rows.astype({c: float for c in features(rows)})


def log_move(rows: pd.DataFrame) -> pd.Series:
    """The log of each release's move, at least `FLOOR`."""
    return np.log(np.maximum(rows[ANSWER].astype(float), FLOOR))


def above(rows: pd.DataFrame, event: float) -> pd.Series:
    """1 where the release moved more than `event`, else 0."""
    return (rows[ANSWER] > event).astype(int)


class Boost(BaseEstimator, RegressorMixin):
    """LightGBM's regression of the log move, forecasting with its first `trees_` trees: the number
    of trees is a setting chosen by predicting the validation year, never by early stopping inside
    the fit (V2-49)."""

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


def valid_loss(score, rows: pd.DataFrame) -> float:
    """How settings are chosen (research R5): the mean log loss of the three chances after a Platt
    scaling on the same releases."""
    x = np.asarray(score, dtype=float).reshape(-1, 1)
    losses = []
    for e in EVENTS:
        y = above(rows, e)
        p = LogisticRegression(C=1e6, max_iter=1000).fit(x, y).predict_proba(x)[:, 1]
        losses.append(log_loss(y, p, labels=[0, 1]))
    return float(np.mean(losses))


def calibrate(score, rows: pd.DataFrame, cutoff) -> dict[float, Dated]:
    """Platt scaling per event (research R3) on `rows`, all known before `cutoff`: a logistic fit of
    "moved more than X" on the forecast. A bigger forecast never lowers a chance."""
    frame = rows[["as_of", KNOWN]].assign(score=score)
    calibrators = {}
    for e in EVENTS:
        cal = Dated(LogisticRegression(C=1e6, max_iter=1000), QUESTION, ["score"])
        cal.fit(frame, cutoff, y=above(rows, e))
        assert cal.estimator.coef_[0, 0] > 0, e
        calibrators[e] = cal
    return calibrators


def in_order(p: dict) -> tuple[dict, int]:
    """The chances put in order (above 20% at most above 10%, at most above 5%), and how many
    releases needed it."""
    fixed = int(((p[0.10] > p[0.05]) | (p[0.20] > np.minimum(p[0.10], p[0.05]))).sum())
    p = dict(p)
    p[0.10] = np.minimum(p[0.10], p[0.05])
    p[0.20] = np.minimum(p[0.20], p[0.10])
    return p, fixed


@dataclass
class ResultsMoveModel:
    """The model for one target year: the trees' forecast, the three calibrations and the band
    edges, each a `Dated` with its cutoff."""

    features: list[str]
    forecast: Dated
    calibrators: dict
    bands: Dated
    setting: dict
    seed: int
    year: int
    trained_through: str
    provenance: dict = field(default_factory=dict)
    tried: dict = field(default_factory=dict, repr=False)  # validation loss per setting and trees
    valid_score: np.ndarray | None = field(default=None, repr=False)  # validation-year forecasts
    question: str = QUESTION
    level: str = "lightgbm"
    eligibility_col: str = ELIGIBILITY

    def chances(self, rows: pd.DataFrame) -> tuple[np.ndarray, dict, int]:
        """The forecast (log move) of `rows`, their three chances in order, and how many releases
        needed ordering."""
        score = self.forecast.predict(rows)
        frame = rows[["as_of"]].assign(score=score)
        p, fixed = in_order({e: self.calibrators[e].predict(frame) for e in EVENTS})
        return score, p, fixed


def fit(rows: pd.DataFrame, year: int = TARGET_YEAR, cols: list[str] | None = None,
        seed: int = SEED, setting: dict | None = None, provenance: dict | None = None,
        start=None) -> ResultsMoveModel:  # fmt: skip
    """The model for target `year` from learnable `rows` (see the module's docstring). With
    `setting` (`params`, `trees`) only that setting is fitted, as the hypothesis checks do; with
    `start`, the trees learn only from releases dated from it (the notebook's 2012 check)."""
    fold = eda.folds(rows, QUESTION, [year])[year]
    inner = fold["inner"] if start is None else fold["inner"] & (rows["as_of"] >= start)
    valid = rows[fold["valid"]]
    cols = list(cols or features(rows))
    target = log_move(rows[inner])
    model_cutoff, cutoff = pd.Timestamp(year - 1, 1, 1), pd.Timestamp(year, 1, 1)
    tried, fitted = {}, {}
    for params in [setting["params"]] if setting else GRID:
        n = setting["trees"] if setting else max(TREES)
        trees = Dated(Boost(params, n, seed), QUESTION, cols).fit(rows[inner], model_cutoff,
                                                                  y=target)  # fmt: skip
        fitted[str(params)] = trees
        for k in [n] if setting else TREES:
            trees.estimator.trees_ = k
            tried[(str(params), k)] = valid_loss(trees.predict(valid), valid)
    best_params, best_trees = min(tried, key=tried.get)
    trees = fitted[best_params]
    trees.estimator.trees_ = best_trees
    score = trees.predict(valid)
    calibrators = calibrate(score, valid, cutoff)
    frame = valid[["as_of", KNOWN]].assign(score=score)
    bands = Dated(Bands(), QUESTION, ["score"]).fit(frame, cutoff, y=valid[ANSWER])
    return ResultsMoveModel(cols, trees, calibrators, bands,
                            {"params": trees.estimator.params, "trees": best_trees}, seed, year,
                            str(rows.loc[inner, KNOWN].max().date()), provenance or {},
                            {f"{p} {t}": round(v, 5) for (p, t), v in tried.items()},
                            score)  # fmt: skip


def predict(model: ResultsMoveModel, rows: pd.DataFrame) -> pd.DataFrame:
    """One row per row of `rows` (same index): whether it is eligible and, for eligible rows, the
    chances of a move above 5%, 10% and 20% (in order) and the band (1-5) with its name. Every step
    refuses a row dated before its cutoff; a missing column is an error. `prev4_mean` and `n_prev`
    may be missing values (a company's first release, or earlier moves still sealed)."""
    needed = ["cik", "as_of", model.eligibility_col, *model.features]
    missing = [c for c in needed if c not in rows.columns]
    if missing:
        raise KeyError(f"missing columns: {missing}")
    out = pd.DataFrame({
        "cik": rows["cik"].astype(str), "as_of": pd.to_datetime(rows["as_of"]),
        "eligible": rows[model.eligibility_col].fillna(False).astype(bool),
        **{c: np.nan for c in CHANCES},
        "move_band": pd.Series(pd.NA, index=rows.index, dtype="Int64"),
        "move_band_name": pd.Series(pd.NA, index=rows.index, dtype="string"),
    }, index=rows.index)  # fmt: skip
    mask = out["eligible"].to_numpy()
    if not mask.any():
        return out
    sub = rows.loc[mask].assign(as_of=out.loc[mask, "as_of"])
    sub = sub.astype({c: float for c in model.features})
    score, p, _ = model.chances(sub)
    band = model.bands.predict(sub[["as_of"]].assign(score=score))
    for e, c in zip(EVENTS, CHANCES, strict=True):
        out.loc[mask, c] = p[e]
    out.loc[mask, "move_band"] = band
    out.loc[mask, "move_band_name"] = [BAND_NAMES[int(b)] for b in band]
    return out


def save(model: ResultsMoveModel, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, p)


def load(path: Path | str) -> ResultsMoveModel:
    return joblib.load(path)
