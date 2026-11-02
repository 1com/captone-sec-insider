"""3-month expected volatility model (Feature 005).

Forecasts continuous daily volatility over the next 63 trading days, median-adjusted
annualized volatility point forecast, and calibrated 80% prediction interval.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb

from sentinel import eda

SEED = 0
VOL_FLOOR = 1e-4  # 0.01% annualized volatility floor so log(vol) is strictly finite


@dataclass
class VolatilityModel:
    question: str
    level: str
    features: list[str]
    eligibility_col: str
    estimator: Any
    clip_lo: dict[str, float]
    clip_hi: dict[str, float]
    smearing_shift: float
    q10_res: float
    q90_res: float
    seed: int
    git_commit: str
    export_date: str


def _transform_features(
    frame: pd.DataFrame,
    feature_cols: list[str],
    clip_lo: dict[str, float],
    clip_hi: dict[str, float],
) -> np.ndarray:
    arrs = [
        pd.to_numeric(frame[c], errors="coerce")
        .clip(clip_lo.get(c, -np.inf), clip_hi.get(c, np.inf))
        .to_numpy(dtype=np.float32)
        for c in feature_cols
    ]
    return np.column_stack(arrs)


def fit(
    train_df: pd.DataFrame,
    *,
    level: str = "lightgbm",
    val_year: int = 2022,
    feature_cols: list[str] | None = None,
    seed: int = SEED,
    git_commit: str = "frozen",
    export_date: str = "2026-10-30",
) -> VolatilityModel:
    """Fit 3-month volatility forecasting model with 80% empirical prediction interval."""
    df_clean = train_df[
        train_df["eligible_volatility"]
        & train_df["vol_63_future"].notna()
        & (train_df["vol_63_future"] > 0)
    ].copy()

    if feature_cols is None:
        feature_cols = [
            c for c in eda.features(df_clean) if c not in ("cum_split_after", "vol_63_future")
        ]

    val_start = pd.Timestamp(year=val_year, month=1, day=1)
    inner_tr = df_clean[
        (df_clean["as_of"] < val_start) & (df_clean["window_end"] < val_start)
    ].reset_index(drop=True)
    inner_va = df_clean[df_clean["as_of"].dt.year == val_year].reset_index(drop=True)

    clip_lo = {
        c: float(inner_tr[c].quantile(0.01)) for c in feature_cols if inner_tr[c].notna().any()
    }
    clip_hi = {
        c: float(inner_tr[c].quantile(0.99)) for c in feature_cols if inner_tr[c].notna().any()
    }

    X_itr = _transform_features(inner_tr, feature_cols, clip_lo, clip_hi)
    y_itr = np.log(
        np.maximum(inner_tr["vol_63_future"].to_numpy(dtype=np.float32), np.float32(VOL_FLOOR))
    )
    X_iva = _transform_features(inner_va, feature_cols, clip_lo, clip_hi)
    y_iva = np.log(
        np.maximum(inner_va["vol_63_future"].to_numpy(dtype=np.float32), np.float32(VOL_FLOOR))
    )

    if level == "xgboost":
        model = xgb.XGBRegressor(
            tree_method="hist",
            learning_rate=0.04,
            n_estimators=500,
            max_depth=5,
            min_child_weight=15.0,
            colsample_bytree=0.7,
            subsample=0.8,
            reg_alpha=5.0,
            reg_lambda=10.0,
            random_state=seed,
            n_jobs=4,
            early_stopping_rounds=30,
        )
        model.fit(X_itr, y_itr, eval_set=[(X_iva, y_iva)], verbose=False)
        va_pred = model.predict(X_iva)
        best_n = max(int(model.best_iteration or 100), 50)

        clip_lo_tr = {
            c: float(df_clean[c].quantile(0.01)) for c in feature_cols if df_clean[c].notna().any()
        }
        clip_hi_tr = {
            c: float(df_clean[c].quantile(0.99)) for c in feature_cols if df_clean[c].notna().any()
        }
        X_tr = _transform_features(df_clean, feature_cols, clip_lo_tr, clip_hi_tr)
        y_tr = np.log(
            np.maximum(df_clean["vol_63_future"].to_numpy(dtype=np.float32), np.float32(VOL_FLOOR))
        )

        final_est = xgb.XGBRegressor(
            tree_method="hist",
            learning_rate=0.04,
            n_estimators=best_n,
            max_depth=5,
            min_child_weight=15.0,
            colsample_bytree=0.7,
            subsample=0.8,
            reg_alpha=5.0,
            reg_lambda=10.0,
            random_state=seed,
            n_jobs=4,
        )
        final_est.fit(X_tr, y_tr, verbose=False)

    else:
        # Default / LightGBM
        model = lgb.LGBMRegressor(
            objective="regression",
            learning_rate=0.04,
            n_estimators=300,
            num_leaves=31,
            min_child_samples=100,
            colsample_bytree=0.7,
            subsample=0.8,
            reg_alpha=5.0,
            reg_lambda=10.0,
            random_state=seed,
            deterministic=True,
            force_col_wise=True,
            n_jobs=4,
            verbose=-1,
        )
        model.fit(
            X_itr,
            y_itr,
            eval_set=[(X_iva, y_iva)],
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )
        va_pred = model.predict(X_iva)
        best_n = max(int(model.best_iteration_ or 100), 50)

        clip_lo_tr = {
            c: float(df_clean[c].quantile(0.01)) for c in feature_cols if df_clean[c].notna().any()
        }
        clip_hi_tr = {
            c: float(df_clean[c].quantile(0.99)) for c in feature_cols if df_clean[c].notna().any()
        }
        X_tr = _transform_features(df_clean, feature_cols, clip_lo_tr, clip_hi_tr)
        y_tr = np.log(
            np.maximum(df_clean["vol_63_future"].to_numpy(dtype=np.float32), np.float32(VOL_FLOOR))
        )

        final_est = lgb.LGBMRegressor(
            objective="regression",
            learning_rate=0.04,
            n_estimators=best_n,
            num_leaves=31,
            min_child_samples=100,
            colsample_bytree=0.7,
            subsample=0.8,
            reg_alpha=5.0,
            reg_lambda=10.0,
            random_state=seed,
            deterministic=True,
            force_col_wise=True,
            n_jobs=4,
            verbose=-1,
        )
        final_est.fit(X_tr, y_tr)

    smearing_shift = float(np.median(y_iva - va_pred))
    res_va = y_iva - (va_pred + smearing_shift)
    q10_res = float(np.quantile(res_va, 0.10))
    q90_res = float(np.quantile(res_va, 0.90))

    return VolatilityModel(
        question="volatility",
        level=level,
        features=list(feature_cols),
        eligibility_col="eligible_volatility",
        estimator=final_est,
        clip_lo=clip_lo_tr,
        clip_hi=clip_hi_tr,
        smearing_shift=smearing_shift,
        q10_res=q10_res,
        q90_res=q90_res,
        seed=seed,
        git_commit=git_commit,
        export_date=export_date,
    )


def predict(model: VolatilityModel, rows: pd.DataFrame) -> pd.DataFrame:
    """Score `rows` using the frozen volatility model bundle."""
    out = pd.DataFrame(
        {
            "cik": rows["cik"].astype(str),
            "as_of": pd.to_datetime(rows["as_of"]),
            "eligible": rows[model.eligibility_col].fillna(False).astype(bool),
            "vol_forecast": np.nan,
            "vol_low_80": np.nan,
            "vol_high_80": np.nan,
        },
        index=rows.index,
    )

    elig_mask = out["eligible"].to_numpy()
    if not elig_mask.any():
        return out

    sub = rows.loc[elig_mask]
    X = _transform_features(sub, model.features, model.clip_lo, model.clip_hi)
    z_hat = model.estimator.predict(X)
    pred_vol = np.exp(z_hat + model.smearing_shift)
    v_low = np.exp(z_hat + model.smearing_shift + model.q10_res)
    v_high = np.exp(z_hat + model.smearing_shift + model.q90_res)

    out.loc[elig_mask, "vol_forecast"] = np.round(pred_vol, 4)
    out.loc[elig_mask, "vol_low_80"] = np.round(v_low, 4)
    out.loc[elig_mask, "vol_high_80"] = np.round(v_high, 4)
    return out


def save(model: VolatilityModel, path: Path | str) -> None:
    """Save the model bundle to disk."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, p)


def load(path: Path | str) -> VolatilityModel:
    """Load the model bundle from disk."""
    return joblib.load(path)
