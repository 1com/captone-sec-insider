# Contract: what each model notebook records for the report, and what 010 records

The report reads only these records; every number in it comes from them.

## The report record (one per notebook execution)

Written by the last code cell of `notebooks/005-volatility-model.ipynb`,
`006-results-move-model.ipynb` and `007-dilution-model.ipynb` through
`sentinel.models.report.record(question, tables, tags)`: one MLflow run named `report` in the
notebook's experiment (`005-volatility`, `006-results-move`, `007-dilution`), tagged
`report=true` plus the notebook's tags (`git_commit`, `export_date`, `data_hash`, `trial`), with
one artifact `report.json`:

| Key | Content |
|---|---|
| `question` | `volatility`, `results_move` or `dilution` |
| `title`, `feature` | e.g. "Dilution", "007" |
| `approved` | the decision that approved the model (`V2-52`, `V2-55`, `V2-58`) |
| `decisions` | list of the decisions that shaped the model, one line each, with their caveats |
| `deciding` | `{"measure": column name, "label": words, "lower_is_better": bool}` |
| `levels` | the levels, simplest first; `chosen`; `textbook` (the textbook rule's choice) |
| `data` | rows, companies, first and last row date, and the answer's summary (base rate or spread) |
| `folds` | table: per test year the rows learned from, left out and tested |
| `results` | table: one row per level and test year with every measure the notebook reports |
| `choice` | table: per level the mean of the deciding measure, the mean gap to the best, the standard error of the yearly gaps, "as good as the best" |
| `bands` | table: per test year and band the rows, the forecast and what happened |
| `calibration` | table: per test year (and event) ten groups: mean forecast and real rate (dilution, results move) or median forecast and median real volatility (volatility) |
| `coverage` | volatility only: table of the 80% range per test year (multipliers, coverage) |
| `hypotheses` | table: one verdict per hypothesis with its family check and direction check |
| `checks` | optional tables of other checks (results move: training from 2012, long windows) |
| `frozen` | the frozen model: level, setting, cutoffs, trained through, number of features, history years |

Tables are stored as `{"columns": [...], "data": [[...], ...]}` (no index; numbers as JSON
numbers, missing values as `null`). Aggregates only: no table may hold one company's values.

## The holdout record (written by 010's guarded command)

One MLflow run per question in experiment `010-holdout`, tagged `holdout=true`, `question`, the
frozen model's provenance and the run date, with one artifact `holdout.json`: `question`, `date`,
`rows`, and a `results` table in the same shape as the report record's (the chosen level and its
baselines, the deciding measure and the others, on the 2023+ answers), plus `bands` (and
`coverage` for volatility). The report shows it unedited; before it exists, "not run yet".
