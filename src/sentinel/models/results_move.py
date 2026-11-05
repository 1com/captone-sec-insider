"""Results-day move model (Feature 006).

Forecasts the absolute price move on earnings release day, calibrated probabilities
of exceeding 5%, 10%, and 20% moves, and assignment to 5 risk bands.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression

from sentinel import eda

SEED = 0
MOVE_FLOOR = 1e-4  # 1 basis point floor for log transform
THRESHOLDS = (0.05, 0.10, 0.20)
BANDS = 5
DECLARED_EXTRA = ["prev4_mean", "n_prev"]


def to_log_move(y: np.ndarray | pd.Series) -> np.ndarray:
    """Safely transform absolute move to log-scale with a 1bp positive floor."""
    return np.log(np.maximum(np.asarray(y, dtype=float), MOVE_FLOOR))


def from_log_move(z: np.ndarray | pd.Series) -> np.ndarray:
    """Exponentiate log-move back to percentage move."""
    return np.exp(np.asarray(z, dtype=float))


@dataclass
class ResultsMoveModel:
    question: str
    level: str
    features: list[str]
    eligibility_col: str
    clip_low: dict[str, float]
    clip_high: dict[str, float]
    medians: dict[str, float]
    sector_map: dict[str, float]
    sector_codes: dict[str, int]
    global_sector_med: float
    history_by_cik: dict[str, tuple[float, int]]
    estimator: Any
    best_params: dict[str, Any]
    smearing_shift: float
    calibrators: dict[str, IsotonicRegression]
    band_edges: list[float]
    band_stats: pd.DataFrame
    seed: int
    git_commit: str
    export_date: str


def _fit_preprocessor(
    tr: pd.DataFrame, feature_cols: list[str]
) -> tuple[
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, int],
    float,
]:
    clip_low, clip_high, medians = {}, {}, {}
    for c in feature_cols:
        s = pd.to_numeric(tr[c], errors="coerce").astype(float).replace([np.inf, -np.inf], np.nan)
        finite = s.dropna()
        if len(finite):
            q01, q50, q99 = finite.quantile([0.01, 0.50, 0.99])
            clip_low[c], medians[c], clip_high[c] = float(q01), float(q50), float(q99)
        else:
            clip_low[c], medians[c], clip_high[c] = 0.0, 0.0, 0.0
    z_tr = to_log_move(tr["move"])
    global_sec_med = float(np.median(z_tr))
    sec_series = tr["sector"].fillna("Unknown").astype(str)
    sector_map = (
        pd.Series(z_tr, index=tr.index).groupby(sec_series, observed=True).median().to_dict()
    )
    sector_codes = {s: idx for idx, s in enumerate(sorted(sec_series.unique()))}
    return clip_low, clip_high, medians, sector_map, sector_codes, global_sec_med


def _transform_features(
    frame: pd.DataFrame,
    feature_cols: list[str],
    clip_low: dict[str, float],
    clip_high: dict[str, float],
    sector_map: dict[str, float],
    sector_codes: dict[str, int],
    global_sec_med: float,
    history_by_cik: dict[str, tuple[float, int]] | None = None,
) -> pd.DataFrame:
    work = frame.copy()
    if (
        "prev4_mean" not in work.columns or "n_prev" not in work.columns
    ) and history_by_cik is not None:
        ciks = work["cik"].astype(str)
        if "prev4_mean" not in work.columns:
            work["prev4_mean"] = [history_by_cik.get(c, (np.nan, 0))[0] for c in ciks]
        if "n_prev" not in work.columns:
            work["n_prev"] = [history_by_cik.get(c, (np.nan, 0))[1] for c in ciks]

    out = {}
    for c in feature_cols:
        s = pd.to_numeric(work[c], errors="coerce").astype(float).replace([np.inf, -np.inf], np.nan)
        out[c] = s.clip(lower=clip_low[c], upper=clip_high[c]).to_numpy(dtype=np.float32)

    if "prev4_mean" in feature_cols and "n_prev" in feature_cols:
        sec_med = (
            work["sector"]
            .fillna("Unknown")
            .astype(str)
            .map(sector_map)
            .fillna(global_sec_med)
            .to_numpy(dtype=float)
        )
        n_p = (
            pd.to_numeric(work["n_prev"], errors="coerce")
            .fillna(0)
            .clip(0, 4)
            .to_numpy(dtype=float)
        )
        p4 = pd.to_numeric(work["prev4_mean"], errors="coerce").to_numpy(dtype=float)
        w = np.where(np.isfinite(p4) & (n_p > 0), n_p / (n_p + 2.0), 0.0)
        log_p4 = np.where(np.isfinite(p4), to_log_move(np.nan_to_num(p4, nan=MOVE_FLOOR)), sec_med)
        out["shrunk_log_prev4"] = (w * log_p4 + (1.0 - w) * sec_med).astype(np.float32)

    sec_str = work["sector"].fillna("Unknown").astype(str)
    out["sector_log_med"] = (
        sec_str.map(sector_map).fillna(global_sec_med).to_numpy(dtype=np.float32)
    )
    out["sector_code"] = sec_str.map(lambda s: sector_codes.get(s, -1)).to_numpy(dtype=np.float32)
    return pd.DataFrame(out, index=frame.index)


def _extract_history_by_cik(tr: pd.DataFrame) -> dict[str, tuple[float, int]]:
    hist = {}
    for cik, g in tr.sort_values("as_of").groupby("cik", sort=False):
        moves = g["move"].dropna().to_numpy(dtype=float)
        if len(moves):
            hist[str(cik)] = (float(np.mean(moves[-4:])), int(len(moves)))
    return hist


def _fit_isotonic_calibrators(
    pred_log_moves: np.ndarray, actual_moves: np.ndarray
) -> dict[str, IsotonicRegression]:
    calibrators = {}
    for t in THRESHOLDS:
        key = f"p_move_{int(t * 100)}"
        y_binary = (actual_moves > t).astype(int)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
        iso.fit(pred_log_moves, y_binary)
        calibrators[key] = iso
    return calibrators


def _predict_calibrated_probs(
    calibrators: dict[str, IsotonicRegression], pred_log_moves: np.ndarray
) -> dict[str, np.ndarray]:
    p5 = calibrators["p_move_5"].predict(pred_log_moves)
    p10 = np.minimum(calibrators["p_move_10"].predict(pred_log_moves), p5)
    p20 = np.minimum(calibrators["p_move_20"].predict(pred_log_moves), p10)
    return {"p_move_5": p5, "p_move_10": p10, "p_move_20": p20}


def fit(
    train_df: pd.DataFrame,
    *,
    level: str = "lightgbm",
    val_year: int = 2022,
    feature_cols: list[str] | None = None,
    seed: int = SEED,
    tune_grid: list[dict[str, Any]] | None = None,
    store_history: bool = True,
    git_commit: str = "frozen",
    export_date: str = "2026-10-30",
) -> ResultsMoveModel:
    """Fit results-day move model with out-of-sample calibration and risk bands."""
    df_clean = train_df[train_df["eligible"] & train_df["move"].notna()].copy()
    if feature_cols is None:
        snap_features = eda.features(df_clean)
        feature_cols = [c for c in snap_features if c != "cum_split_after"] + DECLARED_EXTRA

    val_start = pd.Timestamp(year=val_year, month=1, day=1)
    inner_tr = df_clean[
        (df_clean["as_of"] < val_start) & (df_clean["close_after"] < val_start)
    ].reset_index(drop=True)
    inner_va = df_clean[df_clean["as_of"].dt.year == val_year].reset_index(drop=True)

    ilow, ihigh, imed, isec_map, isec_codes, iglob = _fit_preprocessor(inner_tr, feature_cols)
    X_itr = _transform_features(inner_tr, feature_cols, ilow, ihigh, isec_map, isec_codes, iglob)
    X_iva = _transform_features(inner_va, feature_cols, ilow, ihigh, isec_map, isec_codes, iglob)
    z_itr = to_log_move(inner_tr["move"])
    z_iva = to_log_move(inner_va["move"])

    best_loss = np.inf
    best_cfg: dict[str, Any] = {}
    best_va_pred = np.zeros(len(inner_va))

    if level == "xgboost":
        if tune_grid is None:
            tune_grid = [
                {
                    "max_depth": 5,
                    "min_child_weight": 15.0,
                    "colsample_bytree": 0.7,
                    "subsample": 0.8,
                }
            ]
        for cfg in tune_grid:
            est = xgb.XGBRegressor(
                tree_method="hist",
                learning_rate=0.04,
                n_estimators=800,
                reg_alpha=5.0,
                reg_lambda=10.0,
                random_state=seed,
                n_jobs=4,
                early_stopping_rounds=40,
                **cfg,
            )
            est.fit(X_itr, z_itr, eval_set=[(X_iva, z_iva)], verbose=False)
            va_pred = est.predict(X_iva)
            loss = float(np.mean(np.abs(va_pred - z_iva)))
            if loss < best_loss:
                best_loss = loss
                best_cfg = {**cfg, "n_estimators": max(int(est.best_iteration or 100), 50)}
                best_va_pred = va_pred

        clow, chigh, cmed, sec_map, sec_codes, glob_med = _fit_preprocessor(df_clean, feature_cols)
        X_tr = _transform_features(
            df_clean, feature_cols, clow, chigh, sec_map, sec_codes, glob_med
        )
        z_tr = to_log_move(df_clean["move"])
        final_est = xgb.XGBRegressor(
            tree_method="hist",
            learning_rate=0.04,
            reg_alpha=5.0,
            reg_lambda=10.0,
            random_state=seed,
            n_jobs=4,
            **best_cfg,
        )
        final_est.fit(X_tr, z_tr, verbose=False)
    else:
        # Default / LightGBM
        if tune_grid is None:
            tune_grid = [
                {
                    "num_leaves": 31,
                    "min_child_samples": 100,
                    "colsample_bytree": 0.7,
                    "subsample": 0.8,
                }
            ]
        for cfg in tune_grid:
            est = lgb.LGBMRegressor(
                objective="regression",
                learning_rate=0.04,
                n_estimators=800,
                reg_alpha=5.0,
                reg_lambda=10.0,
                random_state=seed,
                deterministic=True,
                force_col_wise=True,
                n_jobs=4,
                verbose=-1,
                **cfg,
            )
            est.fit(
                X_itr,
                z_itr,
                eval_set=[(X_iva, z_iva)],
                callbacks=[lgb.early_stopping(40, verbose=False)],
            )
            va_pred = est.predict(X_iva)
            loss = float(np.mean(np.abs(va_pred - z_iva)))
            if loss < best_loss:
                best_loss = loss
                best_cfg = {**cfg, "n_estimators": max(int(est.best_iteration_ or 100), 50)}
                best_va_pred = va_pred

        clow, chigh, cmed, sec_map, sec_codes, glob_med = _fit_preprocessor(df_clean, feature_cols)
        X_tr = _transform_features(
            df_clean, feature_cols, clow, chigh, sec_map, sec_codes, glob_med
        )
        z_tr = to_log_move(df_clean["move"])
        final_est = lgb.LGBMRegressor(
            objective="regression",
            learning_rate=0.04,
            reg_alpha=5.0,
            reg_lambda=10.0,
            random_state=seed,
            deterministic=True,
            force_col_wise=True,
            n_jobs=4,
            verbose=-1,
            **best_cfg,
        )
        final_est.fit(X_tr, z_tr)

    smearing_shift = float(np.median(z_iva - best_va_pred))
    cals = _fit_isotonic_calibrators(best_va_pred, inner_va["move"].to_numpy(dtype=float))

    z_hat_tr = final_est.predict(X_tr)
    pred_move_tr = np.exp(z_hat_tr + smearing_shift)
    band_edges = [float(q) for q in np.quantile(pred_move_tr, [0.2, 0.4, 0.6, 0.8])]
    tr_bands = np.digitize(pred_move_tr, band_edges) + 1
    band_rows = []
    for b in range(1, 6):
        m = df_clean.loc[tr_bands == b, "move"].to_numpy(dtype=float)
        has_m = len(m) > 0
        band_rows.append(
            {
                "band": b,
                "train_n": int(len(m)),
                "median_move": float(np.median(m)) if has_m else np.nan,
                "p25_move": float(np.quantile(m, 0.25)) if has_m else np.nan,
                "p75_move": float(np.quantile(m, 0.75)) if has_m else np.nan,
                "hit_5": float(np.mean(m > 0.05)) if has_m else np.nan,
                "hit_10": float(np.mean(m > 0.10)) if has_m else np.nan,
                "hit_20": float(np.mean(m > 0.20)) if has_m else np.nan,
            }
        )
    band_stats = pd.DataFrame(band_rows).set_index("band")

    return ResultsMoveModel(
        question="results_move",
        level=level,
        features=list(feature_cols),
        eligibility_col="eligible",
        clip_low=clow,
        clip_high=chigh,
        medians=cmed,
        sector_map=sec_map,
        sector_codes=sec_codes,
        global_sector_med=glob_med,
        history_by_cik=_extract_history_by_cik(df_clean) if store_history else {},
        estimator=final_est,
        best_params=best_cfg,
        smearing_shift=smearing_shift,
        calibrators=cals,
        band_edges=band_edges,
        band_stats=band_stats,
        seed=seed,
        git_commit=git_commit,
        export_date=export_date,
    )


def predict(model: ResultsMoveModel, rows: pd.DataFrame) -> pd.DataFrame:
    """Score `rows` using the frozen model bundle."""
    out = pd.DataFrame(
        {
            "cik": rows["cik"].astype(str),
            "as_of": pd.to_datetime(rows["as_of"]),
            "eligible": rows[model.eligibility_col].fillna(False).astype(bool),
            "pred_log_move": np.nan,
            "pred_move": np.nan,
            "band": pd.Series(pd.NA, index=rows.index, dtype="Int64"),
            "p_move_5": np.nan,
            "p_move_10": np.nan,
            "p_move_20": np.nan,
            "band_median": np.nan,
            "band_p25": np.nan,
            "band_p75": np.nan,
        },
        index=rows.index,
    )

    elig_mask = out["eligible"].to_numpy()
    if not elig_mask.any():
        return out

    sub = rows.loc[elig_mask]
    X = _transform_features(
        sub,
        model.features,
        model.clip_low,
        model.clip_high,
        model.sector_map,
        model.sector_codes,
        model.global_sector_med,
        model.history_by_cik,
    )
    z_hat = model.estimator.predict(X)
    pred_m = np.exp(z_hat + model.smearing_shift)
    probs = _predict_calibrated_probs(model.calibrators, z_hat)
    bands = np.digitize(pred_m, model.band_edges) + 1

    out.loc[elig_mask, "pred_log_move"] = z_hat
    out.loc[elig_mask, "pred_move"] = pred_m
    out.loc[elig_mask, "band"] = bands
    out.loc[elig_mask, "p_move_5"] = probs["p_move_5"]
    out.loc[elig_mask, "p_move_10"] = probs["p_move_10"]
    out.loc[elig_mask, "p_move_20"] = probs["p_move_20"]
    out.loc[elig_mask, "band_median"] = model.band_stats.loc[bands, "median_move"].to_numpy()
    out.loc[elig_mask, "band_p25"] = model.band_stats.loc[bands, "p25_move"].to_numpy()
    out.loc[elig_mask, "band_p75"] = model.band_stats.loc[bands, "p75_move"].to_numpy()
    return out


def save(model: ResultsMoveModel, path: Path | str) -> None:
    """Save the model bundle to disk."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, p)


def load(path: Path | str) -> ResultsMoveModel:
    """Load the model bundle from disk."""
    return joblib.load(path)
