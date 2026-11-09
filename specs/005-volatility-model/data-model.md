# Data model: Volatility model (005)

What the notebook works with, from the rows it reads to the object it freezes.

## Training row (input, `data/exports/ml/volatility.parquet`, read only)

A company at a month end, read through `sentinel.eda.load("volatility")` (dated by 31 Dec 2022;
the newest rows are of September 2022, whose windows end by December).

| Column | Role |
|---|---|
| `cik`, `as_of` | the company and the month end (the row's date); sort keys, never inputs |
| `window_end` | the last session of the next 63: the day the answer is known (`eda.WINDOW_END`); folds and `Dated` cutoffs |
| `vol_63_future` | the answer: the annualised volatility of the next 63 sessions |
| `vol_63` | the past 63 sessions' volatility: an input, the naive baseline and the rule's one input |
| `eligible_volatility` | this question's flag (V2-26: price-only stocks count when they pass the price rules) |
| `coverage` | full, foreign or price_only: never an input; used to report price-only stocks apart |
| the 95 features of `eda.features()` | inputs |
| `sector`, `cum_split_after`, other flags | never inputs (`sector` is the current SIC, not point-in-time; `cum_split_after` is look-ahead) |

Derived per row: `log_vol = log(vol_63_future)` (rows with an answer of 0 are left out); the
forecast error `error = forecast − log_vol`.

Validation: `eligible_volatility` true, the answer present and above 0; every `window_end` on or
before 31 Dec 2022 (`eda.check_folds` refuses otherwise).

## Fold (walk-forward years 2014–2022; target year 2023 for the frozen model)

From `eda.folds(rows, "volatility", years)`: masks `inner`, `gap`, `valid`, `purged`, `test`,
checked by `eda.check_folds`. Years 2019–2022 are the scored test years; 2014–2018 are forecast
only to give the 80% range its earlier years' errors (V2-10). Cutoffs: 1 January of Y−1 for the
forecasts, 1 January of Y for settings, the range and the band edges.

## Level (four, simplest first)

`baseline` (log `vol_63`), `rule` (`a + b · log vol_63`), `ridge`, `lightgbm`. Each gives, per row,
one forecast of the log volatility.

## Range

For year Y: the 10th and 90th percentiles `q10`, `q90` of the out-of-sample errors of every earlier
year whose answers were known before Y; the range is `exp(forecast − q90)` to `exp(forecast −
q10)` around `exp(forecast)` (errors are forecast minus answer, in logs).

## Band (five)

Edges at the quintiles of the out-of-sample forecasts of the same earlier years; per band and test
year: rows, median forecast, median real volatility, the range's coverage. Names as 006 and 007
("1 · Very low risk" … "5 · Very high risk").

## Result row (one per level and test year; MLflow run)

`level`, `year`, `mae_log` (deciding, V2-56), `rmse_log`, `rank_corr`, `coverage_80`, and the same
for price-only stocks and US filers; the chosen setting; rows.

## Frozen model (`VolatilityModel`, one object)

See [contracts/model-contract.md](contracts/model-contract.md). Fitted for target year 2023 → saved
(joblib, MLflow artifact) → loaded by 009 and 010.
