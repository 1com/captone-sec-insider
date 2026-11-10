"""The simpler levels of the three approved models (V2-60): the code of each notebook's levels,
moved here unchanged so that the holdout test (010) can make them for 2023 exactly as for a test
year and score them beside the frozen models. `sentinel holdout --freeze-levels` first re-runs
them on the test years 2019-2022 and requires every measure to equal the notebook's record (008).

- dilution (`notebooks/007-dilution-model.ipynb`, sections 2-5): the base rate, the offering rule,
  a logistic regression calibrated by Platt scaling on the validation year;
- results move (`006-results-move-model`, sections 2-5): the base rates (the floor), the baseline
  `prev4_mean`, the rule, a ridge regression, each with the three Platt calibrations of
  `results_move.calibrate`;
- volatility (`005-volatility-model`, sections 2-5): the baseline, the mean-reversion rule, a ridge
  regression of the change, each with its 80% range set on its own out-of-sample history from 2014
  (V2-10).

Every fitted step is a `Dated` (V2-49), as in the notebooks.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin, TransformerMixin
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from sentinel import eda
from sentinel.models import dilution, results_move, volatility
from sentinel.models.dated import Dated

SEED = 0


def valid_start(year: int) -> pd.Timestamp:
    """The cutoff of a forecast judged on year `year`: answers known before its validation year."""
    return pd.Timestamp(year - 1, 1, 1)


def test_start(year: int) -> pd.Timestamp:
    """The cutoff of the settings, calibrations, ranges and band edges used on year `year`."""
    return pd.Timestamp(year, 1, 1)


class Clip(BaseEstimator, TransformerMixin):
    """Cut each column at its 1st and 99th percentiles of the rows it was fitted on."""

    def __init__(self, lower=0.01, upper=0.99):
        self.lower, self.upper = lower, upper

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        self.lo_ = np.nanquantile(X, self.lower, axis=0)
        self.hi_ = np.nanquantile(X, self.upper, axis=0)
        return self

    def transform(self, X):
        return np.clip(np.asarray(X, dtype=float), self.lo_, self.hi_)


class Logs(BaseEstimator, TransformerMixin):
    """The log (at least `floor`) of the columns `cols` among `columns`; the others unchanged."""

    def __init__(self, columns, cols, floor=1e-4):
        self.columns, self.cols, self.floor = columns, cols, floor

    def fit(self, X, y=None):
        self.idx_ = [self.columns.index(c) for c in self.cols if c in self.columns]
        return self

    def transform(self, X):
        X = np.array(X, dtype=float)
        X[:, self.idx_] = np.log(np.maximum(X[:, self.idx_], self.floor))
        return X


def redundant(frame: pd.DataFrame, cols: list[str], keep: set[str]) -> list[str]:
    """One of each |Spearman| >= 0.9 pair (the notebooks' rule), keeping the columns of `keep`."""
    pairs = eda.redundant_pairs(frame, cols, threshold=0.9, seed=SEED)
    out = []
    for a, b in zip(pairs.a, pairs.b, strict=True):
        if a in out or b in out or (a in keep and b in keep):
            continue
        out.append(a if b in keep else b)
    return out


@dataclass
class Level:
    """One simpler level made for one target year: its fitted `Dated` steps and its setting."""

    question: str
    level: str
    year: int
    steps: dict
    setting: dict = field(default_factory=dict)


# --- dilution (007) ---------------------------------------------------------------------------

D_ANSWER = dilution.ANSWER
D_LEVELS = ["base_rate", "rule", "logistic"]
D_KEEP = {"log_addv20", "log_market_cap", "log_close"}


class BaseRate(BaseEstimator, ClassifierMixin):
    """The rows' dilution rate, the same chance for every row."""

    def fit(self, X, y):
        self.rate_ = float(np.mean(y))
        return self

    def predict_proba(self, X):
        p = np.full(len(X), self.rate_)
        return np.column_stack([1 - p, p])


class OfferingRule(BaseEstimator, ClassifierMixin):
    """The dilution rate of the rows with an offering filed in the last 12 months, and of the
    others."""

    def fit(self, X, y):
        flag, y = np.asarray(X, dtype=float)[:, 0] > 0, np.asarray(y)
        self.rates_ = {"flagged": float(y[flag].mean()), "not": float(y[~flag].mean())}
        return self

    def predict_proba(self, X):
        flag = np.asarray(X, dtype=float)[:, 0] > 0
        p = np.where(flag, self.rates_["flagged"], self.rates_["not"])
        return np.column_stack([1 - p, p])


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def dilution_linear(rows: pd.DataFrame) -> list[str]:
    """The logistic regression's columns: the features without macro and short volume, one of each
    redundant pair found on the 2019 fold's training rows."""
    feats = [c for c in eda.features(rows) if c not in dilution.LOOK_AHEAD]
    cand = [c for c in feats if eda.family(c) not in ("macro", "short volume")]
    f19 = eda.folds(rows, D_ANSWER, [2019])[2019]
    train = f19["inner"] | f19["gap"] | f19["valid"]
    drop = redundant(rows[train], cand, D_KEEP)
    return [c for c in cand if c not in drop]


def _logistic(C: float):
    return make_pipeline(
        Clip(),
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        LogisticRegression(C=C, max_iter=3000),
    )


def dilution_fit(rows: pd.DataFrame, year: int, linear: list[str]) -> dict[str, Level]:
    """The three simpler levels for target `year` (sections 3-5 of the notebook)."""
    f = eda.folds(rows, D_ANSWER, [year])[year]
    train = f["inner"] | f["gap"] | f["valid"]
    y = rows[D_ANSWER].astype(int)
    base = Dated(BaseRate(), D_ANSWER, []).fit(rows[train], test_start(year))
    rule = Dated(OfferingRule(), D_ANSWER, ["n_offering_12m"]).fit(rows[train], test_start(year))
    tried = {}
    for C in (0.01, 0.1, 1.0):
        model = Dated(_logistic(C), D_ANSWER, linear).fit(rows[f["inner"]], valid_start(year))
        p = model.predict(rows[f["valid"]])
        tried[C] = (log_loss(y[f["valid"]], p), model, p)
    C = min(tried, key=lambda c: tried[c][0])
    _, model, p_valid = tried[C]
    frame = rows.loc[f["valid"], ["as_of", "window_end"]].assign(logit=_logit(p_valid))
    cal = Dated(LogisticRegression(C=1e6), D_ANSWER, ["logit"]).fit(
        frame, test_start(year), y=y[f["valid"]]
    )
    assert cal.estimator.coef_[0, 0] > 0
    return {
        "base_rate": Level("dilution", "base_rate", year, {"model": base}),
        "rule": Level("dilution", "rule", year, {"model": rule}),
        "logistic": Level(
            "dilution", "logistic", year, {"model": model, "calibrator": cal}, {"C": C}
        ),
    }


def dilution_predict(level: Level, rows: pd.DataFrame) -> dict:
    """The chance of each row."""
    p = level.steps["model"].predict(rows)
    if "calibrator" in level.steps:
        p = level.steps["calibrator"].predict(rows[["as_of"]].assign(logit=_logit(p)))
    return {"p": np.asarray(p, dtype=float)}


def dilution_scores(rows: pd.DataFrame, out: dict) -> dict:
    """Log loss (deciding), AUC, Brier score and top-tenth lift (the notebook's `scores`)."""
    p = np.clip(np.asarray(out["p"], dtype=float), 1e-6, 1 - 1e-6)
    yt, ps = pd.Series(rows[D_ANSWER].astype(int).to_numpy(dtype=float)), pd.Series(p)
    return {
        "log_loss": log_loss(yt, p, labels=[0, 1]),
        "auc": eda.auc(yt, ps),
        "brier": brier_score_loss(yt, p),
        "lift_top10": eda.top_decile_lift(yt, ps),
    }


def dilution_walk(rows: pd.DataFrame, years) -> pd.DataFrame:
    """The simpler levels' measures on the walk-forward test `years`, scored as in the notebook."""
    linear, out = dilution_linear(rows), []
    for year in years:
        test = rows[eda.folds(rows, D_ANSWER, [year])[year]["test"]]
        for name, level in dilution_fit(rows, year, linear).items():
            out.append(
                {
                    "level": name,
                    "year": year,
                    **dilution_scores(test, dilution_predict(level, test)),
                }
            )
    return pd.DataFrame(out)


# --- results move (006) -----------------------------------------------------------------------

R = results_move
R_LEVELS = ["base_rate", "baseline", "rule", "ridge"]
R_VOL = ["vol_21", "vol_63", "vol_252", "range_vol_21", "idio_vol_252"]
R_LOGGED = ["prev4_mean", *R_VOL]
R_KEEP = {
    "log_addv20",
    "log_market_cap",
    "log_close",
    "idio_vol_252",
    "vol_63",
    "prev4_mean",
    "n_prev",
}
R_RULE = ["prev4_mean", "n_prev", "vol_63"]


class Rate(BaseEstimator, ClassifierMixin):
    """The share of the releases it learns from that moved more than an event's size."""

    def fit(self, X, y):
        self.rate_ = float(np.mean(y))
        return self

    def predict_proba(self, X):
        p = np.full(len(X), self.rate_)
        return np.column_stack([1 - p, p])


class PreviousFour(BaseEstimator, RegressorMixin):
    """The log of the mean of the company's previous four moves; a company's first release gets
    the typical (median) log move of the releases it learned from."""

    def fit(self, X, y):
        self.first_ = float(np.median(y))
        return self

    def predict(self, X):
        prev4 = np.asarray(X, dtype=float)[:, 0]
        return np.where(np.isfinite(prev4), np.log(np.maximum(prev4, R.FLOOR)), self.first_)


class MoveRule(BaseEstimator, RegressorMixin):
    """log move = a + b * history + c * log(vol_63); history is log(prev4_mean) pulled toward the
    typical release's log move by m / (m + k), m = min(n_prev, 4); a, b, c by least squares."""

    def __init__(self, k=2):
        self.k = k

    def _parts(self, X):
        X = np.asarray(X, dtype=float)
        prev4, n_prev, vol = X[:, 0], X[:, 1], X[:, 2]
        m = np.minimum(np.nan_to_num(n_prev), 4)
        w = m / (m + self.k)
        own = np.where(np.isfinite(prev4), np.log(np.maximum(prev4, R.FLOOR)), self.typical_)
        vol = np.where(np.isfinite(vol) & (vol > 0), vol, self.vol_)
        return np.column_stack([w * own + (1 - w) * self.typical_, np.log(vol)])

    def fit(self, X, y):
        self.typical_ = float(np.median(y))
        v = np.asarray(X, dtype=float)[:, 2]
        self.vol_ = float(np.nanmedian(v[v > 0]))
        self.lr_ = LinearRegression().fit(self._parts(X), y)
        return self

    def predict(self, X):
        return self.lr_.predict(self._parts(X))


def move_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """The learnable releases with the notebook's derived columns."""
    rows = R.learnable(raw)
    derived = {
        "log_move": R.log_move(rows),
        **{f"above_{round(e * 100)}": R.above(rows, e) for e in R.EVENTS},
    }
    return pd.concat([rows, pd.DataFrame(derived, index=rows.index)], axis=1).copy()


def move_linear(rows: pd.DataFrame) -> list[str]:
    """The ridge's columns: the inputs, one of each redundant pair (2019 fold's inner rows)."""
    feats = R.features(rows)
    drop = redundant(rows[eda.folds(rows, R.QUESTION, [2019])[2019]["inner"]], feats, R_KEEP)
    return [c for c in feats if c not in drop]


def _ridge_move(alpha: float, cols: list[str]):
    return make_pipeline(
        Logs(list(cols), R_LOGGED, R.FLOOR),
        Clip(),
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        Ridge(alpha=alpha),
    )


def _move_level(make, features, rows, f, year, grid) -> Level:
    """The notebook's `fit_level`: learn from the inner rows, choose the setting by the
    validation year's loss, calibrate there."""
    inner, valid = rows[f["inner"]], rows[f["valid"]]
    tried = {}
    for params in grid:
        model = Dated(make(**params), R.QUESTION, features)
        model.fit(inner, valid_start(year), y=inner["log_move"])
        s = model.predict(valid)
        tried[str(params)] = (R.valid_loss(s, valid), params, model, s)
    _, params, model, s_valid = min(tried.values(), key=lambda t: t[0])
    cals = R.calibrate(s_valid, valid, test_start(year))
    return Level(
        "results_move", "", year, {"model": model, **{str(e): c for e, c in cals.items()}}, params
    )


def move_fit(rows: pd.DataFrame, year: int, linear: list[str]) -> dict[str, Level]:
    """The four simpler levels for target `year` (sections 3-5 of the notebook)."""
    f = eda.folds(rows, R.QUESTION, [year])[year]
    train = rows[f["inner"] | f["gap"] | f["valid"]]
    rates = {
        str(e): Dated(Rate(), R.QUESTION, []).fit(
            train, test_start(year), y=train[f"above_{round(e * 100)}"]
        )
        for e in R.EVENTS
    }
    out = {
        "base_rate": Level(
            "results_move",
            "base_rate",
            year,
            rates,
            {"median_move": float(train[R.ANSWER].median())},
        )
    }
    makers = {
        "baseline": (PreviousFour, ["prev4_mean"], [{}]),
        "rule": (MoveRule, R_RULE, [{"k": k} for k in (1, 2, 4)]),
        "ridge": (
            lambda alpha: _ridge_move(alpha, linear),
            linear,
            [{"alpha": a} for a in (1.0, 10.0, 100.0, 1000.0)],
        ),
    }
    for name, (make, feats, grid) in makers.items():
        level = _move_level(make, feats, rows, f, year, grid)
        level.level = name
        out[name] = level
    return out


def move_predict(level: Level, rows: pd.DataFrame) -> dict:
    """The three chances (in order) and the typical size of each release."""
    if level.level == "base_rate":
        p = {e: level.steps[str(e)].predict(rows) for e in R.EVENTS}
        return {"p": p, "size": np.full(len(rows), level.setting["median_move"])}
    score = level.steps["model"].predict(rows)
    frame = rows[["as_of"]].assign(score=score)
    p, _ = R.in_order({e: level.steps[str(e)].predict(frame) for e in R.EVENTS})
    return {"p": p, "size": np.exp(score)}


def move_scores(rows: pd.DataFrame, out: dict) -> dict:
    """The notebook's `scores`: per event log loss and Brier score, their mean log loss
    (deciding), the rank correlation of the chance above 10% with the move, the absolute and log
    errors of the typical size."""
    m = {}
    for e in R.EVENTS:
        yt = (rows[R.ANSWER] > e).astype(int).to_numpy()
        pe = np.clip(out["p"][e], 1e-6, 1 - 1e-6)
        m[f"log_loss_{round(e * 100)}"] = log_loss(yt, pe, labels=[0, 1])
        m[f"brier_{round(e * 100)}"] = brier_score_loss(yt, pe)
    m["log_loss_mean"] = float(np.mean([m[f"log_loss_{round(e * 100)}"] for e in R.EVENTS]))
    move = rows[R.ANSWER].to_numpy()
    m["rank_corr"] = float(pd.Series(out["p"][0.10]).corr(pd.Series(move), method="spearman"))
    size = out["size"]
    m["mae"] = float(np.mean(np.abs(size - move)))
    m["mae_log"] = float(
        np.mean(np.abs(np.log(np.maximum(size, R.FLOOR)) - np.log(np.maximum(move, R.FLOOR))))
    )
    return m


def move_walk(rows: pd.DataFrame, years) -> pd.DataFrame:
    """The simpler levels' measures on the walk-forward test `years`, scored as in the notebook."""
    linear, out = move_linear(rows), []
    for year in years:
        test = rows[eda.folds(rows, R.QUESTION, [year])[year]["test"]]
        for name, level in move_fit(rows, year, linear).items():
            out.append(
                {"level": name, "year": year, **move_scores(test, move_predict(level, test))}
            )
    return pd.DataFrame(out)


# --- volatility (005) -------------------------------------------------------------------------

V = volatility
V_LEVELS = ["baseline", "rule", "ridge"]
V_KEEP = {"log_addv20", "log_market_cap", "log_close", "idio_vol_252", "vol_63"}
V_VOL = ["vol_21", "vol_63", "vol_252", "range_vol_21", "idio_vol_252"]


class VolBaseline(BaseEstimator, RegressorMixin):
    """log(vol_63): the past three months' volatility, assumed to continue."""

    def fit(self, X, y):
        return self

    def predict(self, X):
        return V.past_of(X)


class VolRule(BaseEstimator, RegressorMixin):
    """log(future) = a + b * log(vol_63), by least squares."""

    def fit(self, X, y):
        self.lr_ = LinearRegression().fit(V.past_of(X).reshape(-1, 1), y)
        return self

    def predict(self, X):
        return self.lr_.predict(V.past_of(X).reshape(-1, 1))


def vol_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """The learnable rows with the notebook's derived columns."""
    rows = V.learnable(raw)
    derived = {
        "log_vol": np.log(rows[V.ANSWER]),
        "log_past": np.log(np.maximum(rows["vol_63"], V.FLOOR)),
        "price_only": rows["coverage"].eq("price_only"),
    }
    return pd.concat([rows, pd.DataFrame(derived, index=rows.index)], axis=1).copy()


def vol_linear(rows: pd.DataFrame) -> list[str]:
    """The ridge's columns: the inputs, one of each redundant pair (2019 fold's inner rows)."""
    feats = V.features(rows)
    drop = redundant(rows[eda.folds(rows, V.QUESTION, [2019])[2019]["inner"]], feats, V_KEEP)
    return [c for c in feats if c not in drop]


def _ridge_vol(alpha: float, cols: list[str]) -> Dated:
    pipe = make_pipeline(
        Logs(list(cols), V_VOL, V.FLOOR),
        Clip(),
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        Ridge(alpha=alpha),
    )
    return Dated(V.Change(pipe, list(cols)), V.QUESTION, V.with_past(cols))


def _vol_forecast(name: str, rows, f, year, linear) -> tuple:
    """The notebook's `fit_level` for one level: learn from the inner rows, choose the setting by
    the validation year's mean absolute log error."""
    grid = {
        "baseline": [{}],
        "rule": [{}],
        "ridge": [{"alpha": a} for a in (1.0, 10.0, 100.0, 1000.0)],
    }
    make = {
        "baseline": lambda: Dated(VolBaseline(), V.QUESTION, ["vol_63"]),
        "rule": lambda: Dated(VolRule(), V.QUESTION, ["vol_63"]),
        "ridge": lambda alpha: _ridge_vol(alpha, linear),
    }[name]
    inner, valid = rows[f["inner"]], rows[f["valid"]]
    tried = {}
    for params in grid[name]:
        model = make(**params)
        model.fit(inner, valid_start(year), y=inner["log_vol"])
        loss = float(
            np.mean(np.abs(np.asarray(model.predict(valid)) - valid["log_vol"].to_numpy()))
        )
        tried[str(params)] = (loss, params, model)
    _, params, model = min(tried.values(), key=lambda t: t[0])
    return model, params


def vol_history(rows: pd.DataFrame, name: str, years, linear) -> tuple[pd.DataFrame, dict]:
    """A level's out-of-sample forecasts and errors for each walk-forward year (the notebook's
    `run`), and its fitted forecast per year."""
    hist, fits = [], {}
    for year in years:
        f = eda.folds(rows, V.QUESTION, [year])[year]
        model, params = _vol_forecast(name, rows, f, year, linear)
        test = rows[f["test"]]
        forecast = model.predict(test)
        hist.append(
            pd.DataFrame(
                {
                    "as_of": test["as_of"],
                    "window_end": test["window_end"],
                    "forecast": forecast,
                    "error": forecast - test["log_vol"].to_numpy(),
                    "year": year,
                },
                index=test.index,
            )
        )
        fits[year] = (model, params)
    return pd.concat(hist), fits


def _vol_level(name: str, year: int, model, params, hist: pd.DataFrame) -> Level:
    h = hist[(hist["year"] < year) & (hist["window_end"] < test_start(year))]
    rng = Dated(V.Range(), V.QUESTION, ["forecast"]).fit(h, test_start(year), y=h["error"])
    return Level("volatility", name, year, {"model": model, "range": rng}, params)


def vol_predict(level: Level, rows: pd.DataFrame) -> dict:
    """The log forecast and its 80% range."""
    forecast = level.steps["model"].predict(rows)
    low, high = level.steps["range"].predict(rows[["as_of"]].assign(forecast=forecast)).T
    return {"forecast": np.asarray(forecast, dtype=float), "low": low, "high": high}


def vol_scores(rows: pd.DataFrame, out: dict) -> dict:
    """The notebook's `scores`: mean absolute log error (deciding), root mean squared log error,
    rank correlation, the 80% range's coverage; price-only stocks and US filers apart."""
    y = np.log(rows[V.ANSWER].to_numpy(dtype=float))
    forecast = out["forecast"]
    err, inside = forecast - y, (y >= out["low"]) & (y <= out["high"])
    po = rows["coverage"].eq("price_only").to_numpy()
    return {
        "mae_log": float(np.mean(np.abs(err))),
        "rmse_log": float(np.sqrt(np.mean(err**2))),
        "rank_corr": float(pd.Series(forecast).corr(pd.Series(y), method="spearman")),
        "coverage_80": float(inside.mean()),
        "mae_log_filers": float(np.mean(np.abs(err[~po]))),
        "mae_log_price_only": float(np.mean(np.abs(err[po]))) if po.any() else np.nan,
        "coverage_price_only": float(inside[po].mean()) if po.any() else np.nan,
        "rows": int(len(y)),
        "rows_price_only": int(po.sum()),
    }


def vol_walk_and_fit(
    rows: pd.DataFrame, years, target: int, first: int = V.FIRST_YEAR
) -> tuple[pd.DataFrame, dict[str, Level]]:
    """The simpler levels' measures on the walk-forward test `years` (as the notebook ran them),
    and the levels made for `target`; one out-of-sample history per level, from `first`."""
    linear, out, frozen = vol_linear(rows), [], {}
    for name in V_LEVELS:
        hist, fits = vol_history(rows, name, range(first, target), linear)
        for year in years:
            test = rows[eda.folds(rows, V.QUESTION, [year])[year]["test"]]
            level = _vol_level(name, year, *fits[year], hist)
            out.append({"level": name, "year": year, **vol_scores(test, vol_predict(level, test))})
        f = eda.folds(rows, V.QUESTION, [target])[target]
        model, params = _vol_forecast(name, rows, f, target, linear)
        frozen[name] = _vol_level(name, target, model, params, hist)
    return pd.DataFrame(out), frozen
