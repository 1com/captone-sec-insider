# Contract: the frozen volatility model

What 009 (daily scores) and 010 (the holdout test) can rely on. Implemented in
`src/sentinel/models/volatility.py` (approved 9 Nov, V2-58; replacing Gemini's module, whose range
was scaled on its training rows and covered 65–67%, audit of 4 Nov); the notebook imports it and
gives the same numbers. The object also keeps `history_years`, the years behind its range.

## The object: `VolatilityModel`

| Field | Type | Meaning |
|---|---|---|
| `level` | str | `baseline`, `rule`, `ridge` or `lightgbm` |
| `features` | list[str] | input columns, selected by name from the rows |
| `forecast` | `Dated` | the level's forecast of log volatility; cutoff 1 Jan 2022 for the frozen model (answers known before it) |
| `range` | `Dated` | the 10th and 90th percentiles of the out-of-sample log errors of all earlier years (V2-10); cutoff 1 Jan 2023 |
| `bands` | `Dated` | four inner edges of the forecast splitting rows into bands 1–5; cutoff 1 Jan 2023 |
| `setting` | dict | the chosen setting (leaves, rows per leaf, trees; or alpha) |
| `eligibility_col` | str | `"eligible_volatility"`: only rows where it is true are scored |
| `seed` | int | 0 |
| `year` | int | 2023, the target year |
| `trained_through` | str | the last `window_end` among the rows the forecast learned from |
| `provenance` | dict | `git_commit`, `export_date`, `data_hash` |
| `question` | str | `"volatility"` |

Saved with `joblib` as one file and logged as an MLflow artifact of the run tagged `frozen`.

## The function: `predict(model, rows) -> DataFrame`

- **Input**: a DataFrame with `cik`, `as_of`, `model.eligibility_col` and every column in
  `model.features`. Extra columns are ignored; a missing column is an error. Rows dated before a
  step's cutoff are refused (`Dated`).
- **Output**: one row per input row (same index): `cik`, `as_of`, `eligible`, and for eligible
  rows `vol_forecast` (the expected annualised volatility, the middle of the range),
  `vol_low_80` and `vol_high_80` (the 80% range, `vol_low_80 < vol_forecast < vol_high_80`),
  `vol_band` (1–5) and `vol_band_name`; empty for the others.
- **Guarantees**: deterministic; never reads an answer; every preprocessing step is inside
  `model`, fitted before its cutoff.

## Use by 009 and 010

- **010** computes the 2023+ answers inside its guarded command, scores the frozen model and
  compares its mean absolute log error and its range's coverage with the baseline's.
- **009** (after 010, V2-42): `forecast_val` is `vol_forecast`, `band` is `vol_band` (the model's
  bands replace the fixed volatility cut-offs of Gemini's daily scoring), and `extra_json` holds
  the range and the band name.
