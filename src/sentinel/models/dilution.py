"""Dilution risk model (Feature 007).

Forecasts the 6-month chance of share dilution (shares up 10%+), calibrated
probabilities, and assignment to 5 risk bands.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from sentinel import config, eda

SEED = 0
BAND_CUTOFFS = [0.02, 0.05, 0.10, 0.20]
BAND_NAMES = {
    1: "1 · Very low risk",
    2: "2 · Low risk",
    3: "3 · Moderate risk",
    4: "4 · Elevated risk",
    5: "5 · High / Imminent risk",
}


@dataclass
class DilutionModel:
    question: str
    level: str
    features: list[str]
    eligibility_col: str
    estimator: Any
    calibrator: IsotonicRegression
    clip_lo: dict[str, float]
    clip_hi: dict[str, float]
    band_edges: list[float]
    band_stats: pd.DataFrame
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
    exclude_split_cases: bool = True,
    split_cases_path: Path | str | None = None,
    git_commit: str = "frozen",
    export_date: str = "2026-10-30",
) -> DilutionModel:
    """Fit dilution forecasting model with out-of-sample isotonic calibration."""
    df_clean = train_df[train_df["eligible_dilution"] & train_df["dilution"].notna()].copy()

    # Exclude the 46 split false-positive cases if requested
    if exclude_split_cases:
        p = config.paths()
        cases_file = (
            Path(split_cases_path)
            if split_cases_path
            else p.exports / "share" / "dilution_split_46_cases.csv"
        )
        if cases_file.exists():
            split_cases = pd.read_csv(cases_file)
            bad_pairs = set(
                zip(
                    split_cases["cik"].astype(str),
                    pd.to_datetime(split_cases["as_of"]).dt.date,
                    strict=False,
                )
            )
            df_clean = (
                df_clean[
                    ~df_clean.apply(
                        lambda r: (str(r["cik"]), r["as_of"].date()) in bad_pairs, axis=1
                    )
                ]
                .copy()
                .reset_index(drop=True)
            )

    if feature_cols is None:
        all_features = eda.features(df_clean)
        feature_cols = [
            c
            for c in all_features
            if eda.family(c) not in ("insider", "macro") and c != "cum_split_after"
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
    y_itr = inner_tr["dilution"].to_numpy(dtype=int)
    X_iva = _transform_features(inner_va, feature_cols, clip_lo, clip_hi)
    y_iva = inner_va["dilution"].to_numpy(dtype=int)

    if level == "xgboost":
        model = xgb.XGBClassifier(
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
            early_stopping_rounds=40,
        )
        model.fit(X_itr, y_itr, eval_set=[(X_iva, y_iva)], verbose=False)
        p_va_raw = model.predict_proba(X_iva)[:, 1]
        best_n = max(int(model.best_iteration or 100), 50)

        clip_lo_tr = {
            c: float(df_clean[c].quantile(0.01)) for c in feature_cols if df_clean[c].notna().any()
        }
        clip_hi_tr = {
            c: float(df_clean[c].quantile(0.99)) for c in feature_cols if df_clean[c].notna().any()
        }
        X_tr = _transform_features(df_clean, feature_cols, clip_lo_tr, clip_hi_tr)
        y_tr = df_clean["dilution"].to_numpy(dtype=int)

        final_est = xgb.XGBClassifier(
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

    elif level == "hist_gradient_boosting":
        model = HistGradientBoostingClassifier(
            learning_rate=0.04,
            max_iter=300,
            max_leaf_nodes=31,
            min_samples_leaf=100,
            l2_regularization=10.0,
            random_state=seed,
            early_stopping=True,
            n_iter_no_change=20,
        )
        model.fit(X_itr, y_itr)
        p_va_raw = model.predict_proba(X_iva)[:, 1]
        best_n = max(int(model.n_iter_ or 100), 50)

        clip_lo_tr = {
            c: float(df_clean[c].quantile(0.01)) for c in feature_cols if df_clean[c].notna().any()
        }
        clip_hi_tr = {
            c: float(df_clean[c].quantile(0.99)) for c in feature_cols if df_clean[c].notna().any()
        }
        X_tr = _transform_features(df_clean, feature_cols, clip_lo_tr, clip_hi_tr)
        y_tr = df_clean["dilution"].to_numpy(dtype=int)

        final_est = HistGradientBoostingClassifier(
            learning_rate=0.04,
            max_iter=best_n,
            max_leaf_nodes=31,
            min_samples_leaf=100,
            l2_regularization=10.0,
            random_state=seed,
            early_stopping=False,
        )
        final_est.fit(X_tr, y_tr)

    else:
        # Default / LightGBM
        model = lgb.LGBMClassifier(
            objective="binary",
            learning_rate=0.04,
            n_estimators=500,
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
            callbacks=[lgb.early_stopping(40, verbose=False)],
        )
        p_va_raw = model.predict_proba(X_iva)[:, 1]
        best_n = max(int(model.best_iteration_ or 100), 50)

        clip_lo_tr = {
            c: float(df_clean[c].quantile(0.01)) for c in feature_cols if df_clean[c].notna().any()
        }
        clip_hi_tr = {
            c: float(df_clean[c].quantile(0.99)) for c in feature_cols if df_clean[c].notna().any()
        }
        X_tr = _transform_features(df_clean, feature_cols, clip_lo_tr, clip_hi_tr)
        y_tr = df_clean["dilution"].to_numpy(dtype=int)

        final_est = lgb.LGBMClassifier(
            objective="binary",
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

    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
    calibrator.fit(p_va_raw, y_iva)

    # Compute training band stats
    p_tr_raw = final_est.predict_proba(X_tr)[:, 1]
    p_tr_cal = calibrator.predict(p_tr_raw)
    tr_bands = np.digitize(p_tr_cal, BAND_CUTOFFS) + 1
    band_rows = []
    for b in range(1, 6):
        mask = tr_bands == b
        y_b = y_tr[mask] if mask.any() else np.array([])
        band_rows.append(
            {
                "band": b,
                "name": BAND_NAMES[b],
                "train_n": int(len(y_b)),
                "actual_rate": float(np.mean(y_b)) if len(y_b) else np.nan,
                "mean_predicted": float(np.mean(p_tr_cal[mask])) if mask.any() else np.nan,
            }
        )
    band_stats = pd.DataFrame(band_rows).set_index("band")

    return DilutionModel(
        question="dilution",
        level=level,
        features=list(feature_cols),
        eligibility_col="eligible_dilution",
        estimator=final_est,
        calibrator=calibrator,
        clip_lo=clip_lo_tr,
        clip_hi=clip_hi_tr,
        band_edges=BAND_CUTOFFS,
        band_stats=band_stats,
        seed=seed,
        git_commit=git_commit,
        export_date=export_date,
    )


def predict(model: DilutionModel, rows: pd.DataFrame) -> pd.DataFrame:
    """Score `rows` using the frozen dilution model bundle."""
    out = pd.DataFrame(
        {
            "cik": rows["cik"].astype(str),
            "as_of": pd.to_datetime(rows["as_of"]),
            "eligible": rows[model.eligibility_col].fillna(False).astype(bool),
            "dilution_prob": np.nan,
            "dilution_band": pd.Series(pd.NA, index=rows.index, dtype="Int64"),
            "dilution_band_name": pd.Series(pd.NA, index=rows.index, dtype="string"),
        },
        index=rows.index,
    )

    elig_mask = out["eligible"].to_numpy()
    if not elig_mask.any():
        return out

    sub = rows.loc[elig_mask]
    X = _transform_features(sub, model.features, model.clip_lo, model.clip_hi)
    p_raw = model.estimator.predict_proba(X)[:, 1]
    p_cal = model.calibrator.predict(p_raw)
    bands = np.digitize(p_cal, model.band_edges) + 1
    band_names = [BAND_NAMES[b] for b in bands]

    out.loc[elig_mask, "dilution_prob"] = np.round(p_cal, 4)
    out.loc[elig_mask, "dilution_band"] = bands
    out.loc[elig_mask, "dilution_band_name"] = band_names
    return out


def save(model: DilutionModel, path: Path | str) -> None:
    """Save the model bundle to disk."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, p)


def load(path: Path | str) -> DilutionModel:
    """Load the model bundle from disk."""
    return joblib.load(path)
