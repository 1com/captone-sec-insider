# Contract: the frozen dilution model

What 009 (daily scores) and 010 (the holdout test) can rely on. Defined in the notebook now and
moved unchanged to `src/sentinel/models/dilution.py` after approval.

## The object: `DilutionModel`

| Field | Type | Meaning |
|---|---|---|
| `level` | str | `base_rate`, `rule`, `logistic` or `lightgbm` |
| `features` | list[str] | input columns, in order; selected by name from the rows |
| `eligibility` | str | `"eligible_dilution"`: only rows where it is true are scored |
| `estimator` | object | fitted preprocessing + model (or the rule's two chances / the constant) |
| `calibrator` | object or None | Platt scaling on the model's log-odds (None for levels 0–1) |
| `band_edges` | list[float] | four inner edges splitting chances into bands 1–5 |
| `seed` | int | 0 |
| `git_commit` | str | commit the model was fitted at |
| `export_date` | str | date of `dilution.parquet` (e.g. `2026-10-30`) |
| `data_hash` | str | first 12 hex of the file's SHA-256 |
| `trained_through` | str | last `window_end` in the training rows (≤ `2022-12-31`) |

Saved with `joblib` as one file, logged as an MLflow artifact of the run tagged
`frozen=candidate`.

## The function: `predict(model, rows) -> DataFrame`

- **Input**: a DataFrame holding at least `cik`, `as_of`, `model.eligibility` and every column in
  `model.features` (as in `dilution.parquet`, `latest.parquet`, `feature_snapshot.parquet`).
  Extra columns are ignored; a missing feature column is an error.
- **Output**: one row per input row with `model.eligibility` true: `cik`, `as_of`, `chance`
  (float in [0, 1]), `band` (int 1–5). Ineligible rows are left out.
- **Guarantees**: deterministic (same rows → identical output); never reads an answer; all
  preprocessing is inside `model` (nothing is fitted on the rows being scored).
