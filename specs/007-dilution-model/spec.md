# Feature Specification: Dilution model

**Feature Branch**: `007-dilution-model`

**Created**: 2026-11-01

**Status**: Second version after the researcher's answers (2 Nov: V2-35 to V2-39)

**Input**: User description: "Feature 007 · Dilution model (roadmap 007, issue #78, owner: the
teammate `sonson033`, with the coding agent): the chance that a company's shares outstanding rise
10% or more within 182 days, built, run and tuned in `notebooks/007-dilution-model.ipynb` under the
evaluation fixed in D60, holdout-ready, approved by the researcher before its code moves to
`src/sentinel/models/`."

## Context

A retail investor holding a small, cash-burning company can lose much of their stake's value when
the company sells new shares: every existing share becomes a smaller slice. The platform shows a
**dilution chance** for every covered US company (D62: dilution first, with its own probability),
always as one of five bands with that band's past hit rate (D47), never as a bare number.

The question and its answer are pre-registered (`config/risk_params.yaml` v5, tag
`prereg-risk-v5`) and are not changed by this feature:

| | |
|---|---|
| One row | a company at a month end, 2012 – June 2022 (`data/exports/ml/dilution.parquet`) |
| Answer `dilution` | 1 if split-adjusted shares outstanding, as first filed, rise by 10% or more between the last count filed by the month end and the last count filed within the next 182 days; 0 if not; missing if no new count was filed |
| Rows to learn from | `eligible_dilution` true and the answer present: 409,576 rows, 6,300 US companies (foreign filers left out, V2-27) |
| Base rate | 9.59%; always forecasting it scores a Brier score of 0.0867 |
| Features | 96, known at the row's close (price, trading, size, financials, filing events, insider, short volume, macro) |

The EDA (`notebooks/004-eda-dilution.ipynb`, section 11) found: the rule "an offering was filed in
the last 12 months" already reaches an AUC of 0.71–0.74 in every test year; the strongest features
are offerings and shelf filings, share growth, interest coverage, R&D intensity, stock-based pay,
volatility, price and size; macro and short volume carry nothing; missing financials carry meaning;
46 "yes" answers whose increase equals a split remain doubtful. The pipeline's cleaning is frozen
(V2-33): any further cleaning is part of this model.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Compare the four levels and choose one (Priority: P1)

The teammate builds the four levels required by D60 in the model notebook: (0) the base rate,
(1) a simple rule, (2) a classic model, (3) gradient-boosted trees. Each is trained only on years
before each test year (2019, 2020, 2021, 2022), with training rows purged whose 182-day window
reaches into the test year, and scored on that test year. One table shows every level against
every test year; the simplest level within one standard error of the best is chosen. The
researcher reads the executed notebook and sees how the choice was made.

**Why this priority**: without a fair comparison against the base rate and the rule there is no
honest answer to "is a model worth showing at all?", and every later step builds on the choice.

**Independent Test**: run the notebook start to finish by one command; it ends with the comparison
table and a named choice.

**Acceptance Scenarios**:

1. **Given** the current export, **When** the notebook runs start to finish, **Then** it shows,
   per test year, the training rows, purged rows and test rows, and every level's AUC, log loss,
   Brier score and lift in the top tenth.
2. **Given** the comparison table, **When** the reader looks for the choice, **Then** it names the
   level, states the mean and standard error of each level, and explains why the chosen level is
   the simplest within one standard error of the best.
3. **Given** the rule level, **When** it is scored, **Then** it reproduces the EDA's offering-rule
   result within rounding (AUC about 0.71–0.74 per test year).
4. **Given** a chosen level that does not clearly beat the rule in every test year, **When** the
   findings are written, **Then** they say so plainly and recommend the rule (or no forecast)
   rather than the model.

---

### User Story 2 - Calibrated chances in five bands (Priority: P2)

The chosen level's chances are calibrated on earlier years only and grouped into five bands. For
each band and test year the notebook shows the forecast chance and the real dilution rate, so the
app can show "companies in this band diluted X% of the time".

**Why this priority**: the product never shows a bare probability (D47, D62); bands with hit rates
are what the user actually sees.

**Independent Test**: from the chosen level's test-year forecasts, the band table and a calibration
chart can be produced and read on their own.

**Acceptance Scenarios**:

1. **Given** the chosen level, **When** calibration is applied, **Then** the calibration is fitted
   only on years before each test year, never on the test year itself.
2. **Given** the five bands, **When** the reader compares them, **Then** the real dilution rate
   rises from the lowest to the highest band in every test year, and each band's forecast and real
   rate are shown side by side.

---

### User Story 3 - Understand what the model uses (Priority: P3)

The notebook shows which features the chosen level relies on (importance or coefficients) and
checks that they make sense and that none leaks the answer. Per D60, the value of the insider and
macro families is measured by refitting without them (five seeds).

**Why this priority**: the researcher must be able to trust and explain the forecast; a leak would
make every number meaningless.

**Independent Test**: the importance table and the family refit results can be read without the
rest of the notebook.

**Acceptance Scenarios**:

1. **Given** the chosen level, **When** its strongest features are listed, **Then** each is a
   feature known at the row's close, and none of the answer, its window end, identifiers or flags
   appears among the inputs.
2. **Given** the family check, **When** insider or macro features are removed, **Then** the change
   in skill is shown with its spread over five seeds.

---

### User Story 4 - A model ready for the one holdout test (Priority: P4)

The chosen model is saved as one frozen object that the guarded holdout command (feature 010) can
score without the notebook. A dry run on the 2023-and-later feature rows (which carry no answers)
proves it scores them without error.

**Why this priority**: the holdout test runs once, on 16 November; a model that cannot be scored
then has no test result.

**Independent Test**: load the saved object in a fresh session and score the 2023+ feature rows.

**Acceptance Scenarios**:

1. **Given** the saved object, **When** it is loaded, **Then** it holds its feature list (selected
   by name), all preprocessing, the eligibility flag, the seed, the git commit and the export date.
2. **Given** the 2023+ feature rows, **When** the dry run scores them, **Then** every eligible row
   gets a chance and a band, and no answer for those years is computed or read.
3. **Given** two runs from the same commit and export, **When** their predictions are compared,
   **Then** they are identical.

### Edge Cases

- **Missing financials** (e.g. no interest coverage for a company without debt): handled with
  "was missing" indicators in the classic model, not by dropping the rows.
- **Extreme ratios** (e.g. leverage up to 1.8 million): cut at the 1st and 99th percentiles of each
  fold's training rows, never using the test year's values.
- **Share growth capped at 20×** and the 46 split-like "yes" answers: the check that finds them
  needs the full database, which the teammate's machine does not have; the researcher exports the
  list and the model drops them in its preprocessing (V2-39; until then they stay in, 0.12% of the
  "yes" answers, research R2).
- **The 2022 test year is half a year** (22,597 rows, January–June): its results are reported with
  that caveat.
- **A company appears in many rows over time**: rows are never split at random; every split is by
  date.
- **Very small bands**: if a band has too few rows in a test year to give a stable rate, this is
  shown, not hidden.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The model MUST learn and be tested only on rows with `eligible_dilution` true and a
  present answer, dated 2022 or earlier, read through the project's development-row loader.
- **FR-002**: The model MUST NOT use as inputs the answer, its window end, the company identifier,
  the row date, any eligibility/coverage flag, or `cum_split_after` (the product of split ratios
  *after* the row's day: look-ahead, research R1).
- **FR-003**: The model MUST NOT read the private reference copies (`data/exports/reference/`) or
  compute or read any answer whose window starts in 2023 or later.
- **FR-004**: Every evaluation MUST be walk-forward by date: for each test year 2019–2022, train on
  earlier years only, with training rows purged whose 182-day window reaches into the test year.
  No random split anywhere, including inside training for tuning. The folds MUST come from
  `eda.folds` and pass `eda.check_folds` (5 Nov): inner rows (answers known before the validation
  year) for the models, the validation year for settings, calibration and band edges.
- **FR-005**: Four levels MUST be built and scored: the base rate, a rule (at least the offering
  rule found by the EDA), a classic model, and gradient-boosted trees.
- **FR-006**: Every level MUST be scored per test year with AUC, log loss, Brier score (stated next
  to the base rate's 0.0867) and lift in the top tenth.
- **FR-007**: The chosen level MUST be the simplest within one standard error of the best on the
  primary measure, with the reasoning written out; the standard error is that of the four yearly
  differences from the best level (V2-50, 5 Nov).
- **FR-008**: Model-side cleaning (V2-33) MUST be fitted on each fold's training rows only: extreme
  ratios cut at the 1st/99th percentiles, missing values filled with the training median plus
  "was missing" indicators, one feature of each highly redundant pair, macro and short-volume
  features left out of the classic model.
- **FR-009**: Hyper-parameters MUST be chosen by time-ordered validation inside the training years,
  never on the test year; no early stopping inside a fit: the number of trees is chosen by
  predicting the validation year (V2-49, 5 Nov).
- **FR-010**: Chances MUST be calibrated on earlier years only and grouped into five bands, each
  with its real dilution rate per test year.
- **FR-011**: The notebook MUST show the chosen level's strongest features and the insider/macro
  family refit check over five seeds.
- **FR-012**: Each run MUST be logged with its settings, results, git commit and data (export)
  version, with fixed seeds so that two runs give identical predictions.
- **FR-013**: The chosen model MUST be saved as one frozen object with its feature list, all
  preprocessing, the eligibility flag, seed, commit and export date, plus one scoring function
  taking the model and feature rows; a dry run on the 2023+ feature rows MUST succeed. Its model,
  calibration and band edges are `Dated` steps that keep their cutoffs (V2-49).
- **FR-014**: The notebook MUST run start to finish by one command and MUST be committed without
  outputs; written findings MUST quote aggregates only (no Tiingo-derived values of single rows).
- **FR-015**: The notebook MUST end with plain-language findings: the chosen level and why, its
  skill per test year against the base rate and the rule, the bands and their hit rates, what moves
  to `src/sentinel/models/`, and open questions.
- **FR-016**: After the researcher approves the level, the model's code MUST move into
  `src/sentinel/models/` with tests, and the notebook MUST then use that code and give the same
  numbers.
- **FR-017** (5 Nov, V2-49): Every fitted step (each model, calibration and set of band edges) MUST
  be a `sentinel.models.dated.Dated`: it learns only from rows whose answers were known before its
  cutoff and refuses to forecast rows dated before it.
- **FR-018** (5 Nov, V2-39, V2-40): The split-like "yes" answers MUST be dropped from the learnable
  rows, found by code (`sentinel.validation.split_dilution`), not read from a file; the holdout test
  (010) MUST drop them from the 2023+ answers by the same rule.
- **FR-019** (5 Nov, V2-46): The notebook MUST end with a verdict on each dilution hypothesis of
  `docs/hypotheses.md` (H-D1 to H-D5): a family check on the chosen level (five seeds, every fold)
  and a direction check per test year.

### Key Entities

- **Training row**: a company at a month end with its 96 features, its eligibility flag and its
  answer (dilution yes/no within 182 days).
- **Fold**: one test year (2019–2022) with its earlier, purged training rows.
- **Level**: one way of forecasting (base rate, rule, classic model, trees) with its scores per fold.
- **Band**: one of five groups of forecasts by chance, with its real dilution rate per test year.
- **Frozen model**: the chosen level as one saved object with everything needed to score new rows.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The notebook runs start to finish from a fresh clone plus the private export by one
  command, without errors.
- **SC-002**: Two runs from the same commit and export give identical predictions for every row.
- **SC-003**: Every level is reported for all four test years with all four measures; the chosen
  level is named with its reasoning.
- **SC-004**: The chosen level beats the base rate's Brier score (0.0867) in every test year; if it
  does not also clearly beat the offering rule (AUC about 0.73) in every test year, the findings
  recommend the rule.
- **SC-005**: Across the five bands the real dilution rate rises from the lowest to the highest band
  in every test year.
- **SC-006**: The frozen model scores 100% of the eligible 2023+ feature rows in the dry run, and no
  2023+ answer is computed or read.
- **SC-007**: The researcher approves the chosen level after reading the executed notebook.

## Assumptions

- The export of 30 October 2026 (`data/exports/ml/dilution.parquet`, cleaning V2-22 to V2-32) is
  the data of record; a later export means re-running the notebook.
- The primary measure for the one-standard-error rule is log loss (a proper score for chances), with
  AUC, Brier score and lift reported alongside (confirmed by the researcher, V2-37).
- The classic model is a regularised logistic regression; the trees are LightGBM, both already in
  the project.
- Run logging uses MLflow, already a project dependency.
- The trees leave out the insider and macro families (V2-36). The 46 split-like "yes" answers
  are dropped once the researcher's list arrives (V2-39, research R2).
- The notebook runs on the teammate's Mac; it does not need the full database, only the export.
- Out of scope: changing the pre-registered definition, the offering-event question (roadmap 024),
  the daily scoring (009), the report (008) and the holdout test itself (010).
