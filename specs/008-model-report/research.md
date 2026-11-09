# Research: Model report and model card data (008)

Decisions taken while planning (9 Nov), each with why and what else was considered.

## R1 · The report's numbers come from records the notebooks write

- **Decision**: each approved model notebook ends with one cell that records the tables the
  report needs as one JSON artifact in an MLflow run named `report` (contracts/report-record.md),
  through one shared function `sentinel.models.report.record`. `sentinel report` reads these
  records and fits nothing.
- **Rationale**: the notebooks are where the models are built and judged; they already hold every
  table. Recording them as they are computed keeps one source of truth; the command stays fast and
  can never disagree with the notebooks. The per-level metrics already in MLflow are not enough
  (no bands, choice, verdicts or frozen setting).
- **Alternatives**: recompute everything in the command with the packaged models (the baseline,
  rule and classic levels live only in the notebooks; minutes of fitting per question; two codes
  for one result); read the notebooks' outputs (never committed; fragile).

## R2 · One export for the whole report

- **Decision**: the three notebooks are re-run once, one after the other, on the same export (9
  November), each with its recording cell; the report names each record's export date and data
  hash. 006 and 005 must give exactly the numbers of their approved runs (same export). 007 was
  approved on the export of 5 November; the daily updates since may have changed a few
  development rows: any difference is shown in the report next to the approved numbers, not
  hidden.
- **Rationale**: a report built from runs on different data would compare unlike things; the
  frozen models for the holdout test are built from the current export.

## R3 · Which records are read

- **Decision**: per experiment, the newest run named `report` with tags `report=true` and
  `trial=False`; the report names its run, commit, export date and data hash. A missing record stops
  the command with the notebook to run.
- **Rationale**: trial runs, older notebook versions (Gemini's experiments, 005's first run) and
  re-runs share the store; the newest complete record of the approved notebook is the one to show.

## R4 · Where and how the report is written

- **Decision**: `docs/report/model_report.md`, figures in `docs/report/figures/`, the model card
  data in `docs/report/model_card.json`; committed (aggregates only). Markdown tables are rendered by
  a small function of the module (no new dependency; pandas needs `tabulate` for Markdown). Figures
  are matplotlib PNGs saved without metadata, so two runs give identical bytes. No date of
  generation in the files (FR-006); each section names its record instead.
- **Gemini's files** (`docs/model_report.md`, `docs/figures/*.png`, `src/sentinel/models/report.py`,
  `tests/unit/test_model_report.py`): replaced; the pull request lists them.

## R5 · What each section holds

Per question, in this order: the question and its answer (from `config/risk_params.yaml` and the
record), the record's provenance, the data, the method, the decisions and their caveats, the
results (the deciding measure: level × test year; then the other measures), the choice, the
calibration chart (dilution, results move) or the forecast-against-real chart and the range's
coverage (volatility), the bands, the hypotheses, other checks, the frozen model, and the holdout
section. A short summary table of the three questions opens the report.

## R6 · The model card data

- **Decision**: one JSON with, per question, the chosen level, the deciding measure per test year
  for the chosen and simpler levels, the band table per test year and pooled over the four years,
  the volatility range's coverage and the holdout results when they exist (contracts/model-card.md).
  The app reads it (011).

## R7 · Tests

- A temporary MLflow store with three synthetic records (and a trial record, and an older record)
  written by `record`; the command writes into a temporary folder: every number in the tables is
  the recorded one; trial records are ignored; a missing question stops it; two runs give identical
  bytes; the holdout section says "not run yet", and shows a synthetic holdout record when one
  exists.
