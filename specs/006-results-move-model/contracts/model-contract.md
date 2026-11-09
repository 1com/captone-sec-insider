# Contract: the frozen results-move model

What 009 (daily scores) and 010 (the holdout test) can rely on. Defined in the notebook now and
moved unchanged to `src/sentinel/models/results_move.py` after the researcher's approval
(replacing Gemini's module and contract of 30 Oct, which were never evaluated as packaged).

## The object: `ResultsMoveModel`

| Field | Type | Meaning |
|---|---|---|
| `level` | str | `baseline`, `rule`, `ridge` or `lightgbm` |
| `features` | list[str] | input columns, selected by name from the rows |
| `forecast` | `Dated` | the level's forecast of the log move; cutoff 1 Jan 2022 (moves known before it) |
| `calibrators` | dict[float, `Dated`] | Platt scaling per event (0.05, 0.10, 0.20) on the forecast; cutoff 1 Jan 2023 |
| `bands` | `Dated` | four inner edges of the forecast (the same order as `p_move_10`: calibration keeps it) splitting releases into bands 1–5; cutoff 1 Jan 2023 |
| `setting` | dict | the chosen setting (e.g. leaves, releases per leaf, trees; or alpha; or k) |
| `eligibility_col` | str | `"eligible"`: only rows where it is true are scored |
| `seed` | int | 0 |
| `year` | int | 2023, the target year |
| `trained_through` | str | the last `close_after` among the rows the forecast learned from |
| `provenance` | dict | `git_commit`, `export_date`, `data_hash` (first 12 hex of the export's SHA-256) |
| `question` | str | `"results_move"` |

Saved with `joblib` as one file and logged as an MLflow artifact of the run tagged
`frozen=candidate`.

## The function: `predict(model, rows) -> DataFrame`

- **Input**: a DataFrame with `cik`, `as_of`, `model.eligibility_col` and every column in
  `model.features`, including `prev4_mean` and `n_prev` (missing values allowed: a company's first
  release, or rows whose earlier moves are sealed). Extra columns are ignored; a missing column is
  an error. Rows dated before a step's cutoff are refused (`Dated`).
- **Output**: one row per input row (same index): `cik`, `as_of`, `eligible`, and for eligible
  rows `p_move_5`, `p_move_10`, `p_move_20` (floats in [0, 1], in order), `move_band` (1–5),
  `move_band_name`; empty for the others.
- **Guarantees**: deterministic (same rows, same output); never reads an answer; every
  preprocessing step is inside `model`, fitted before its cutoff (nothing is fitted on the rows
  being scored).

## Use by 009 and 010

- **010** scores the 2023+ releases computed inside its guarded command (with their `prev4_mean`
  and `n_prev` from the label code with the later end date) and compares the log loss of the
  three chances with the baseline's.
- **009** (after 010, V2-42): `forecast_val` is `p_move_10` (the chance the bands are ordered by,
  V2-53), `band` is `move_band`, and `extra_json` holds the three chances and the band name.
