# Data Model: Results-day move model (006)

## 1. Input Data (`data/exports/ml/results_move.parquet`)

Loaded via `sentinel.eda.load("results_move")` (`as_of <= 2022-12-31`, sorted by `cik, as_of`),
filtered to `eligible == True` and `move.notna()`.

| Column group | Columns | Usage in 006 |
|---|---|---|
| Identifiers & dates | `cik`, `as_of`, `filing_date`, `report_date`, `close_after` | `cik, as_of` identify and sort rows; `as_of` and `close_after` define the walk-forward purge (`as_of < Y-01-01` and `close_after < Y-01-01`); never used as features |
| Eligibility & coverage flags | `month_end`, `release_eve`, `latest`, `coverage`, `filer_type`, `foreign_filer`, `active_filer`, `excluded`, `eligible`, `eligible_volatility`, `eligible_dilution` | Filter to `eligible == True`; never used as features |
| Categorical | `sector` | Fama–French 12 industry; used for sector shrinkage in Level 1 and encoded using training-fold statistics / indicators in Levels 2–3 |
| Declared historical move features | `prev4_mean` (double, nullable), `n_prev` (int, $\ge 0$) | Level 0 baseline (`prev4_mean`), and declared features for Levels 1–3 |
| Snapshot features (97 numeric columns) | Price (`ret_*`, `vol_*`, `range_vol_21`, `max_drawdown_252`, `near_high_252`, `beta_252`, `idio_vol_252`, `log_close`, `close`, `cum_split_after`), trading (`log_addv20`, `addv20`, `zero_volume_63`, `sessions_listed`), size (`market_cap`, `shares_outstanding`, `log_market_cap`), financials (15 ratios/counts), filing events (24 counts/gaps), insider (11 columns), short volume (3 columns), macro (15 columns) | Input features for Levels 2–3 (`vol_63` used in Level 1) |
| Target | `move` (double, $\ge 0$) | Market-adjusted absolute return from `as_of` to `close_after`; never used as a feature |

## 2. Walk-Forward Fold Definition

For each test year $Y \in \{2019, 2020, 2021, 2022\}$:
- **Training set**: eligible rows with `as_of < f"{Y}-01-01"` and `close_after < f"{Y}-01-01"` (and
  `as_of >= train_start` when testing the 2012+ start).
- **Purged rows**: eligible rows with `as_of < f"{Y}-01-01"` and `close_after >= f"{Y}-01-01"`.
- **Test set**: eligible rows with `as_of.dt.year == Y`.

## 3. Fitted Model Bundle (`ResultsMoveModel`)

A single self-contained serialisable Python dataclass saved to MLflow:

| Field | Type | Description |
|---|---|---|
| `question` | `str` | `"results_move"` |
| `level` | `str` | `"level0_baseline"` / `"level1_rule"` / `"level2_ridge"` / `"level3_lgbm"` |
| `features` | `list[str]` | Exact ordered list of input feature names read by `predict` |
| `eligibility_col` | `str` | `"eligible"` |
| `clip_low` | `dict[str, float]` | Training 1st percentile per numeric feature |
| `clip_high` | `dict[str, float]` | Training 99th percentile per numeric feature |
| `medians` | `dict[str, float]` | Training median per numeric feature (for imputation) |
| `missing_flag_cols` | `list[str]` | Features for which a binary `_missing` indicator is added |
| `sector_medians` | `dict[str, float]` | Training median log-move per sector (plus `"_all"` fallback) |
| `history_by_cik` | `dict[str, tuple[float, int]]` | Latest training `(prev4_mean, n_prev)` per CIK for dry-run / daily scoring on snapshot tables |
| `scaler` | `StandardScaler \| None` | Fitted feature scaler (for Ridge) |
| `estimator` | `Any` | Fitted regression estimator predicting $z = \log(\max(\text{move}, 10^{-4}))$ |
| `smearing_shift` | `float` | Median residual shift on training data to map $\hat{z}$ to move scale |
| `calibrators` | `dict[str, IsotonicRegression]` | Fitted calibrators for `"p_move_5"` ($>0.05$), `"p_move_10"` ($>0.10$), `"p_move_20"` ($>0.20$) |
| `band_edges` | `list[float]` | 4 internal quantile cutoffs (20%, 40%, 60%, 80%) on training predicted move |
| `band_stats` | `pd.DataFrame` | Historical reference table per band (1–5): count, median move, p25, p75, hit_5, hit_10, hit_20 |
| `seed` | `int` | `0` |
| `git_commit` | `str` | Git SHA at training time |
| `export_date` | `str` | Modification date of `results_move.parquet` |

## 4. Prediction Output (`predict(model, rows) -> pd.DataFrame`)

Indexed identically to `rows`, with one row per input row (values populated where
`rows[model.eligibility_col]` is true, NaN where ineligible):

| Column | Type | Constraints | Description |
|---|---|---|---|
| `cik` | `str` | copied from input | Company identifier |
| `as_of` | `datetime64[ns]` | copied from input | Feature snapshot date |
| `eligible` | `bool` | copied from input | Eligibility flag |
| `pred_log_move` | `float` | finite where eligible | Predicted log-move $\hat{z}$ |
| `pred_move` | `float` | $> 0$ where eligible | Predicted move size on natural scale |
| `band` | `Int64` | in $\{1, 2, 3, 4, 5\}$ where eligible | Assigned risk band (1 = lowest, 5 = highest) |
| `p_move_5` | `float` | in $[0, 1]$, $\ge \text{p\_move\_10}$ | Calibrated probability of $\text{move} > 5\%$ |
| `p_move_10` | `float` | in $[0, 1]$, $\ge \text{p\_move\_20}$ | Calibrated probability of $\text{move} > 10\%$ |
| `p_move_20` | `float` | in $[0, 1]$ | Calibrated probability of $\text{move} > 20\%$ |
| `band_median` | `float` | $> 0$ where eligible | Historical median move in the assigned band |
| `band_p25` | `float` | $> 0$ where eligible | Historical 25th percentile move in the assigned band |
| `band_p75` | `float` | $\ge \text{band\_p25}$ where eligible | Historical 75th percentile move in the assigned band |
