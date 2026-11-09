# Feature Specification: Volatility model

**Feature Branch**: `005-volatility-model`

**Created**: 2026-11-09

**Status**: First version, written to the decisions of 4–9 Nov (V2-46, V2-48, V2-49, V2-50) before
any clean result

**Input**: User description: "Feature 005 · Volatility model (roadmap 005, issue #67): how much a
stock's price will swing over the next three months, built, run and tuned in
`notebooks/005-volatility-model.ipynb` under the evaluation fixed in D60, shown as a band, a level
and an 80% range (D62) with the range set on all earlier years (V2-10), holdout-ready, approved by
the researcher before its code moves to `src/sentinel/models/`; only if it is approved by the
evening of Wednesday 11 November (V2-48)."

## Context

Volatility is how much a stock's price swings: a stock with an annual volatility of 20% moves
about 1.3% on a typical day, one with 80% about 5%. A retail investor wants to know how wild the
next three months are likely to be, not as one bare number (D62) but as **a level, an 80% range
and one of five bands with that band's past outcomes**: for example "band 4, expected about 45%
a year, 80% likely between 30% and 65%; in the past, stocks in this band swung 47% a year
(median)".

The question and its answer are pre-registered (`config/risk_params.yaml` v5, tag
`prereg-risk-v5`) and are not changed by this feature:

| | |
|---|---|
| One row | a company at a month end, January 2012 – September 2022 (`data/exports/ml/volatility.parquet`) |
| Answer `vol_63_future` | the annualised standard deviation of daily log returns (adjusted close) over the next 63 sessions; missing with fewer than 50 returns; modelled as its logarithm |
| Rows to learn from | `eligible_volatility` true and the answer present and above 0: 530,137 rows, 7,883 companies (export of 9 Nov); 9,484 of them price-only stocks (V2-26); the 93 answers of exactly 0 (a price that never changed in 63 days) have no logarithm and are left out |
| The answer's spread | median 0.36 (±36% a year); 80% of rows between 0.18 and 0.83 |
| Naive baseline (pre-registered) | `vol_63`: the same measure over the previous 63 sessions, assumed to continue |
| Features | the snapshot's features known at the month-end close |

The EDA (`notebooks/004-eda-volatility.ipynb`, Findings) found: the naive baseline already ranks
well (rank correlation 0.79) but misses by about 30% on a typical row (mean absolute log error
0.25–0.49 in 2019–2022), badly in 2020 (the crash). A one-line **mean-reversion rule**,
log(future) = a + b · log(past) with b ≈ 0.78, beats it in three of the four test years.
The strongest features are past volatility in its forms, the fall from the 12-month high, price
level, loss-making, size, interest coverage, R&D intensity and cash share; for the *change* from
past to future volatility, market volatility, VIX and 2-year rate changes. Price-only stocks trade
more thinly and are reported separately. The pipeline's cleaning is frozen (V2-33): any further
cleaning is part of this model.

Gemini's first version (30 Oct – 3 Nov) was not approved (audit of 4 Nov): the one-standard-error
rule was not applied, its 80% range was scaled on the training rows' own errors (it covered 65–67%
of outcomes, not 80%), and its bands were fixed cut-offs without hit rates. This feature starts
the comparison again.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Compare the four levels and choose one (Priority: P1)

The four levels required by D60 are built in the model notebook: (0) the naive baseline (past
volatility continues), (1) the mean-reversion rule, (2) a classic model, (3) LightGBM. Each
forecasts the log of the next three months' volatility. Each learns only from rows whose answers
were known before each test year (2019, 2020, 2021, 2022) and is scored on that test year. One
table shows every level against every test year; the simplest level within one standard error of
the best is chosen, the standard error being that of the four yearly differences (V2-50).

**Why this priority**: without a fair comparison against the baseline and the rule there is no
honest answer to "is a model worth showing at all?".

**Independent Test**: run the notebook start to finish by one command; it ends with the comparison
table and a named choice.

**Acceptance Scenarios**:

1. **Given** the current export, **When** the notebook runs start to finish, **Then** it shows,
   per test year, the training rows, the rows left out by the purge and the test rows.
2. **Given** each level, **When** it is scored, **Then** each test year shows the deciding measure
   and, beside it, the other log errors, the rank correlation with the answer and the 80%
   range's coverage.
3. **Given** the comparison table, **When** the reader looks for the choice, **Then** it names the
   level, shows each level's yearly scores and yearly gaps to the best with their standard
   errors, and explains why the chosen level is the simplest within one standard error.
4. **Given** the rule level, **When** it is scored, **Then** its slope is below 1 and it reproduces
   the EDA's result within rounding (better than the baseline in 2019–2021).

---

### User Story 2 - A level, an honest 80% range and five bands (Priority: P2)

The chosen level's forecast comes with an 80% range whose width is set on the out-of-sample
errors of all earlier years (V2-10): each earlier year forecast by a model that learned only from
the years before it. Forecasts are grouped into five bands; for each band and test year the
notebook shows the forecasts and what happened, so the app can say "stocks in this band swung X%
a year (median), and 8 in 10 stayed inside their range".

**Why this priority**: the product never shows a bare number (D62); an 80% range that holds 80%
of the time, and bands with their outcomes (D47), are what the user sees.

**Independent Test**: the range-coverage table and the band table of the notebook can be read on
their own.

**Acceptance Scenarios**:

1. **Given** a test year, **When** its 80% ranges are set, **Then** they use only errors of rows
   whose answers were known before that year, never the training rows' own errors and never the
   test year's.
2. **Given** the test years, **When** coverage is measured, **Then** the share of answers inside
   their 80% range is shown per year (overall, and for price-only stocks); a year far from 80% is
   explained, not hidden.
3. **Given** the five bands, **When** the reader compares them, **Then** the median real
   volatility rises from the lowest to the highest band in every test year.

---

### User Story 3 - Understand what the model uses and judge the hypotheses (Priority: P3)

The notebook shows which features the chosen level relies on, checks that none leaks the answer,
and ends with a verdict on each volatility hypothesis of `docs/hypotheses.md` (H-V1 to H-V6): a
family check (refit without the family, five seeds, every test year), a direction check (the
expected sign in at least three of four test years), and for H-V6 the level comparison itself.

**Why this priority**: the researcher must be able to trust and explain the forecast; the
verdicts are the report's claims.

**Independent Test**: the importance table, the family checks and the verdict table can be read
without the rest of the notebook.

**Acceptance Scenarios**:

1. **Given** the chosen level, **When** its strongest features are listed, **Then** each is known
   at the row's month-end close, and none of the answer, its window end, identifiers, flags,
   `sector` or `cum_split_after` appears among the inputs.
2. **Given** each hypothesis family, **When** it is removed and the level refitted, **Then** the
   change in the deciding measure is shown with its spread over five seeds, and the verdict
   follows the rule written in `docs/hypotheses.md`.

---

### User Story 4 - A model ready for the one holdout test (Priority: P4)

The chosen model is saved as one frozen object that the guarded holdout command (feature 010)
can score without the notebook. A dry run on the 2023-and-later feature rows (which carry no
answers) proves it scores them without error.

**Why this priority**: the holdout test runs once, on 16 November; a model that cannot be scored
then has no test result.

**Independent Test**: load the saved object in a fresh session and score the 2023+ month-end
feature rows.

**Acceptance Scenarios**:

1. **Given** the saved object, **When** it is loaded, **Then** it holds its feature list (selected
   by name), all preprocessing, the range's multipliers, the band edges, the eligibility flag, the
   seed, the git commit, the export date and the cutoff of every fitted step.
2. **Given** the 2023+ feature rows, **When** the dry run scores them, **Then** every eligible row
   gets a level, a range (low below level below high) and a band, and no answer for those years
   is computed or read.
3. **Given** two runs from the same commit and export, **When** their predictions are compared,
   **Then** they are identical.

### Edge Cases

- **Answers of exactly 0** (93 rows): left out of learning and scoring (no logarithm); the label is
  pre-registered and stays.
- **The 2020 crash**: a calm end of 2019 said nothing about March 2020; every level misses it. The
  year-by-year rule (V2-50) compares levels within each year, and the range's coverage in 2020 is
  shown, not hidden.
- **The 2022 test year is nine months** (rows dated January–September; later windows end after
  2022): reported with that note.
- **Price-only stocks** (9,484 rows): thinner trading; their test years are reported separately.
- **Extreme ratios and missing financials**: cut at the 1st and 99th percentiles of each fit's
  training rows; missing values filled from the training rows with "was missing" indicators.
- **A company appears in many months**: rows are never split at random; every split is by date.
- **The windows overlap** (a row's 63-session window reaches into the next two months' rows):
  rows whose answers are not yet known at a cutoff never teach a model judged from it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The model MUST learn and be tested only on rows with `eligible_volatility` true and a
  present answer above 0, dated 2022 or earlier, read through the project's development-row
  loader.
- **FR-002**: The model MUST NOT use as inputs `vol_63_future`, `window_end`, `cik`, `as_of`, any
  eligibility, coverage or row-type flag, `sector` (the current SIC's sector, not point-in-time)
  or `cum_split_after` (look-ahead).
- **FR-003**: The model MUST NOT read the private reference copies (`data/exports/reference/`) or
  compute or read any answer whose window starts in 2023 or later.
- **FR-004**: Every evaluation MUST be walk-forward by date: for each test year 2019–2022, learn
  only from rows whose answers were known before the period judged, with the purge counted and
  shown. No random split anywhere. The folds MUST come from `eda.folds` and pass
  `eda.check_folds`.
- **FR-005**: Four levels MUST be built and scored, each forecasting the log of the answer: (0) the
  naive baseline `log(vol_63)`; (1) the mean-reversion rule `a + b · log(vol_63)` fitted on earlier
  years; (2) a classic model; (3) LightGBM.
- **FR-006**: The deciding measure MUST be [NEEDS CLARIFICATION: the mean absolute error of the
  log (the EDA's measure) or the root mean squared error of the log?] per test year; the other
  log error, the rank correlation with the answer and the 80% range's coverage MUST be reported
  beside it for every test year.
- **FR-007**: The chosen level MUST be the simplest within one standard error of the best on the
  deciding measure, the standard error being that of the four yearly differences from the best
  level (V2-50), with each level's yearly scores and gaps shown and the reasoning written out.
- **FR-008**: Model-side cleaning (V2-33) MUST be fitted on each fit's training rows only: extreme
  ratios cut at the 1st/99th percentiles, missing values filled from the training rows plus "was
  missing" indicators, one feature of each highly redundant pair in the classic model.
- **FR-009**: Settings MUST be chosen by time-ordered validation inside the training years, never
  on the test year; no early stopping inside a fit (V2-49).
- **FR-010**: The 80% range MUST be the level's forecast scaled by the 10th and 90th percentiles of
  the out-of-sample log errors of all earlier years (V2-10): each earlier year forecast by a model
  that learned only from rows whose answers were known before it; only errors whose answers were
  known before the period judged.
- **FR-011**: Forecasts MUST be grouped into five bands by the forecast level, with edges set on
  earlier years only; each band shows, per test year, its rows, its median forecast, the median
  real volatility and the range's coverage (D47).
- **FR-012**: The notebook MUST report the test years separately for price-only stocks and US
  filers (EDA).
- **FR-013**: The notebook MUST show the chosen level's strongest features and end with a verdict
  on each hypothesis H-V1 to H-V6 (V2-46).
- **FR-014**: Each run MUST be logged with its settings, results, git commit and data (export)
  version, with fixed seeds so that two runs give identical predictions.
- **FR-015**: Every fitted step (each model, the range's multipliers and the band edges) MUST be
  a `sentinel.models.dated.Dated` (V2-49): it learns only from rows whose answers were known
  before its cutoff and refuses to forecast rows dated before it.
- **FR-016**: The chosen model MUST be saved as one frozen object with its feature list, all
  preprocessing, the eligibility flag, seed, commit and export date, plus one scoring function
  taking the model and feature rows; a dry run on the 2023+ month-end feature rows MUST succeed.
- **FR-017**: The notebook MUST run start to finish by one command under the memory cap and MUST
  be committed without outputs; written findings MUST quote aggregates only.
- **FR-018**: The notebook MUST end with plain-language findings: the chosen level and why, its
  skill per test year against the baseline and the rule, the range's coverage, the bands, the
  hypothesis verdicts, what moves to `src/sentinel/models/`, and open questions.
- **FR-019**: After the researcher approves the level, the model's code MUST move into
  `src/sentinel/models/volatility.py` with tests, replacing Gemini's, and the notebook MUST then
  use that code and give the same numbers.

### Key Entities

- **Training row**: a company at a month end with its features, its eligibility flag and its
  answer (the log of next three months' volatility, known at `window_end`).
- **Fold**: one test year (2019–2022) with its inner training rows, validation year and purge.
- **Level**: one way of forecasting the log volatility, with its scores per fold.
- **Range**: the forecast times two multipliers (the 10th and 90th percentiles of earlier years'
  out-of-sample errors), giving the low and high ends of the 80% range.
- **Band**: one of five groups of rows by forecast level, with its outcomes per test year.
- **Frozen model**: the chosen level as one saved object with everything needed to score new rows.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The notebook runs start to finish from a fresh clone plus the private export by one
  command, under the 5 GB memory cap, without errors.
- **SC-002**: Two runs from the same commit and export give identical predictions for every row.
- **SC-003**: Every level is reported for all four test years with every measure; the chosen level
  is named with its reasoning.
- **SC-004**: The chosen level beats the naive baseline on the deciding measure in every test
  year; if it does not also beat the rule in every test year, the findings say so.
- **SC-005**: The 80% range covers between 75% and 85% of the answers in at least three of the four
  test years, and the miss in any other year is explained.
- **SC-006**: Across the five bands the median real volatility rises from the lowest to the
  highest band in every test year.
- **SC-007**: The frozen model scores 100% of the eligible 2023+ month-end feature rows in the dry
  run, and no 2023+ answer is computed or read.
- **SC-008**: The researcher approves the chosen level after reading the executed notebook, by the
  evening of Wednesday 11 November (V2-48); otherwise 005 is left out of the product and the
  holdout test, and the report says why.

## Assumptions

- The export of 9 November 2026 (`data/exports/ml/volatility.parquet`) is the data of record; a
  later export means re-running the notebook.
- The method's open choices are settled in the plan on years before every test year, as for 006
  (a design check on 2016–2018).
- The classic model is a regularised linear regression; the trees are LightGBM, both already in
  the project. Run logging uses MLflow.
- The daily scores (009) score each company's newest row, a day like any month end, so no input
  changes meaning between training and scoring (unlike 006's release eves).
- Out of scope: changing the pre-registered definition, the daily scoring (009), the report (008),
  the app (011–018) and the holdout test itself (010).
