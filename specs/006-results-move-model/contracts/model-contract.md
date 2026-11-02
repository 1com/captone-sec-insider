# Contract: Results-day move model notebook and scoring interface

## 1. Notebook Section Contract (`notebooks/006-results-move-model.ipynb`)

The notebook preserves the top instructional markdown cells and fills all ten numbered sections:

1. **Setup and data**: Load development rows via `sentinel.eda.load("results_move")`, filter to
   `eligible == True` and `move.notna()`, define the allowed feature list (explicitly declaring
   `prev4_mean` and `n_prev`), verify excluded columns are absent, and print rows and companies per
   year.
2. **Walk-forward folds**: Build the four purged folds (test years 2019, 2020, 2021, 2022) where
   training rows satisfy `as_of < Y-01-01` and `close_after < Y-01-01`; print train, purged and test
   counts per fold.
3. **Level 0: the naive baseline**: Score `prev4_mean` (with training-median fallback where
   `n_prev == 0`, plus the constant training median floor) on each test year 2019–2022; report
   Spearman $\rho$, MAE, MedAE, Log MAE, and Brier/log-loss of empirical baseline probabilities.
4. **Level 1: a rule**: Fit and evaluate the shrinkage + volatility rule on each fold's training
   rows only; report per-year and mean ± SE metrics against Level 0.
5. **Level 2: a classic model**: Prune redundant feature pairs ($|\rho| \ge 0.90$ on training rows),
   clip ratios at training 1st/99th percentiles, impute medians with `_missing` flags, standardise,
   and fit `Ridge` on log-move with inner time-ordered validation for `alpha`; report per-year and
   mean ± SE metrics.
6. **Level 3: LightGBM**: Fit gradient-boosted trees on log-move with fixed seed (`SEED = 0`),
   inner time-ordered validation for hyperparameters and early stopping, plus checks for 2012+
   training start; report per-year and mean ± SE metrics.
7. **Comparison and choice**: Single unified comparison table across all four levels and all four
   test years (2019–2022) with mean, standard error, and the 1-SE threshold; apply the 1-SE rule to
   select the winning level; include the window-length check (< 5 days vs all) and 5-seed family
   ablations (without insider, without macro); log runs to MLflow.
8. **Calibration and bands**: Calibrate `p_move_5`, `p_move_10` and `p_move_20` using training data
   only; check predicted vs observed rates per test year and overall (reliability chart, Brier score
   and log loss vs base rate); construct the 5 risk bands and report each band's count, median move,
   interquartile range (p25–p75) and hit rates; run the holdout-readiness dry run on
   `latest.parquet` and 2023+ `feature_snapshot.parquet`.
9. **What the model uses**: Show the strongest features (importance / standardized coefficients and
   signs), verify economic sense and confirm zero leakage.
10. **Findings**: Plain-English summary for the researcher: the chosen level and why, test-year
    skill vs the baseline, calibration and band hit rates, diagnostic results, what moves into
    `src/sentinel/models/`, and any open questions.

## 2. Package Interface Contract (`src/sentinel/models/results_move.py`, Phase 2 after approval)

```python
SEED = 0
THRESHOLDS = (0.05, 0.10, 0.20)
BANDS = 5

def fit(train_df: pd.DataFrame, *, level: str = "chosen", seed: int = SEED) -> ResultsMoveModel:
    """Fit preprocessing, estimator, probability calibrators and 5-band cutoffs on `train_df`."""

def predict(model: ResultsMoveModel, rows: pd.DataFrame) -> pd.DataFrame:
    """Score `rows` using `model.features` by name; returns the forecast DataFrame."""

def evaluate_walk_forward(df: pd.DataFrame) -> dict[str, Any]:
    """Run all 4 levels across 2019-2022 purged folds, log to MLflow, and return tables."""
```
