# Research: The holdout test (010)

Decisions taken while planning (10 Nov), each with why and what else was considered.

## R1 · The rows of record: the export of 9 November, kept

- **Decision**: the export the frozen models were built on (V2-59) was copied before the 10:00
  update of 10 November to `data/frozen/2026-11-09/ml/` (git-ignored, private), with its file
  dates; each file's SHA-256 prefix equals the data hash recorded with its frozen model
  (`42efca98d2e3` dilution, `60d44c447ca6` results move, `284e6f632544` volatility). Every
  simpler level is made from these rows (V2-60), and every step checks the hash first.
- **Rationale**: the daily update replaces the export each weekday; levels made from a later
  export would not be comparable with the frozen models.

## R2 · The simpler levels: the notebooks' code, packaged and proven identical

- **Decision**: the code of each simpler level is moved, unchanged, from its notebook into
  `src/sentinel/models/levels.py` (dilution: base rate, offering rule, logistic regression;
  results move: base rates, baseline, rule, ridge; volatility: baseline, rule, ridge, each with
  its calibration or 80% range). A one-time step, `sentinel holdout --freeze-levels`, first
  re-runs every simpler level for every test year 2019–2022 on the kept rows and requires every
  measure to equal the notebook's record (the 008 report record) to 1e-9; only then does it make
  each level for 2023 exactly as for a test year and record them in MLflow (a run named
  `frozen-levels` in the question's experiment, one artifact). The approved notebooks are not
  edited.
- **Rationale**: "the same code as its notebook" is shown by identical results, not asserted;
  freezing the levels before 16 November keeps the test itself to loading and scoring.
- **Alternatives**: edit the notebooks to import the packaged levels and re-run them (three
  notebook changes after approval, 45 minutes of runs); fit the levels during the test (fitting
  inside the one-time run, a later failure point).
- **Dilution's split-like answers** (V2-39/40) are found in the build database; the step checks
  that the learnable rows it gets equal the record's count (408,181) and keeps the list beside the
  rows (`data/frozen/2026-11-09/split_like.parquet`).

## R3 · The 2023+ answers, in memory only

- **Decision**: the guarded run reads the build database read-only and calls the development
  label functions (`labels.risk.month_labels`, `results_moves`) with the end date moved to the
  newest session of the calendar in the data; month-end rows from 2023 for volatility and
  dilution, every release for the results move's history (`prev4_mean` includes the 2023+ moves
  known by each release); only rows dated from 1 January 2023 are kept. Nothing is written to the
  label tables or the exports. The split-like rule is applied to the 2023+ dilution answers by the
  same code (`validation.split_dilution`, given the answers instead of the label table).
- **The rows**: `feature.snapshot` rows from 2023 joined with the answers exactly as the export
  builds the training files; each question's eligibility; volatility answers of 0 left out.
- **A test** shows that the label functions with a later end date give the development answers
  for every row whose window ended by 2022 (SC-003).

## R4 · The guard and the log

- **Decision**: `sentinel holdout` without an option prints what it would do; `--check` verifies
  the frozen models and levels (V2-59, V2-60), the registration lock and the absence of an earlier
  run, and counts the 2023+ feature rows, computing no answer; `--run` is the test. It refuses if
  experiment `010-holdout` holds any run or `data/holdout/log.jsonl` exists; it writes the records
  (008 contract) and appends the log entry (date, commit, data date, models' provenance, rows,
  record ids). Nothing in the command deletes or overrides them.

## R5 · The measures

- **Decision**: the test years' measures per level (each notebook's): dilution log loss (deciding),
  AUC, Brier, top-tenth lift; results move the mean log loss of the three chances (deciding), each
  event's log loss and Brier, rank correlation, mean absolute and log errors; volatility the mean
  absolute log error (deciding), root mean squared log error, rank correlation, the 80% range's
  coverage, price-only stocks apart. Per calendar year from 2023 and over all; the chosen model's
  bands with what happened in them.
