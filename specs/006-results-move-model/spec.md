# Feature Specification: Results-day move model

**Feature Branch**: `006-results-move-model`

**Created**: 2026-10-30 (Gemini); **rewritten 2026-11-09** after the audit of 4 Nov

**Status**: Second version: rewritten to the decisions of 4–5 Nov (V2-41, V2-46, V2-49, V2-50)
before any clean result; the bands' order decided 9 Nov (V2-53)

**Input**: User description: "Feature 006 · Results-day move model (roadmap 006, issue #77): the
chances that a company's share price moves more than 5%, 10% and 20% beyond the market on its
results day, built, run and tuned in `notebooks/006-results-move-model.ipynb` under the evaluation
fixed in D60, chosen by the mean log loss of the three chances (V2-41), holdout-ready, approved by
the researcher before its code moves to `src/sentinel/models/`."

## Context

When a company publishes its quarterly or annual results, its share price often jumps or falls far
more than on an ordinary day: a stock that usually moves 1–2% a day may move 8% the day after its
results. A retail investor holding the stock before results day wants to know how violent that
move is likely to be. Not its direction, which cannot be forecast reliably, and not one bare
number that pretends to be exact, but **the chances of a move larger than 5%, 10% and 20%**, shown
in one of five bands with that band's past hit rates (D47, D62).

The question and its answer are pre-registered (`config/risk_params.yaml` v5, tag
`prereg-risk-v5`, D61, D63) and are not changed by this feature:

| | |
|---|---|
| One row | a company's results announcement (the last 8-K item 2.02 belonging to a 10-Q or 10-K), 2010–2022 (`data/exports/ml/results_move.parquet`) |
| Answer `move` | the absolute return from the close before the release (`as_of`) to the close after the 8-K was filed (`close_after`), minus SPY's return over the same days |
| The three events | `move` above 0.05, above 0.10, above 0.20 |
| Rows to learn from | `eligible` true and `move` present: 156,926 releases, 5,937 companies (export of 9 Nov); no foreign filers (they file no 8-K item 2.02) |
| Base rates | 39.8% above 5%, 17.1% above 10%, 4.0% above 20%; median move 3.7%, 99th percentile 31% |
| Naive baseline (pre-registered) | `prev4_mean`: the mean of the company's previous four moves (`n_prev` counts them; 1,346 releases are a company's first, with none) |
| Features | the snapshot's features known at `as_of`'s close, plus `prev4_mean` and `n_prev`, without the three release-timing features (V2-54) |

`prev4_mean` uses only earlier moves whose windows had closed before the release's `as_of`
(checked on 9 Nov: 0 of 170,879 rows overlap).

The EDA (`notebooks/004-eda-results-move.ipynb`, Findings) found: the baseline ranks releases
(rank correlation 0.30–0.39 in 2019–2022) but its size is no more accurate than one constant
for everyone; recent volatility ranks the move as well as the company's own history (about 0.33);
then drawdown, distance from the high, beta, loss-making, cash share and size; the tail is long
(model the log of the move or use a quantile loss); financial features are mostly missing in
2010–2011 (consider training from 2012); a small share of windows last 5 days or more (check the
test years with and without them). The pipeline's cleaning is frozen (V2-33): any further cleaning
is part of this model.

Gemini's first version (30 Oct – 3 Nov) is void: it used `cum_split_after` (the product of split
ratios *after* the row's day, a look-ahead input), applied no one-standard-error rule, chose
settings with early stopping, and its packaged model differed from the evaluated one (audit of
4 Nov). Its numbers in MLflow are for reference only; this feature starts the comparison again.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Compare the four levels by their chances and choose one (Priority: P1)

The four levels required by D60 are built in the model notebook: (0) the naive baseline,
(1) a simple rule, (2) a classic model, (3) LightGBM. Each level gives, for every release, three
chances: of a move above 5%, above 10% and above 20%. Each is trained only on releases whose
moves were known before each test year (2019, 2020, 2021, 2022) and scored on that test year. One
table shows every level against every test year; the deciding measure is the mean log loss of the
three chances (V2-41); the simplest level within one standard error of the best is chosen, the
standard error being that of the four yearly differences (V2-50). The researcher reads the
executed notebook and sees how the choice was made.

**Why this priority**: without a fair comparison against the baseline and the rule there is no
honest answer to "is a model worth showing at all?", and every later step builds on the choice.

**Independent Test**: run the notebook start to finish by one command; it ends with the comparison
table and a named choice.

**Acceptance Scenarios**:

1. **Given** the current export, **When** the notebook runs start to finish, **Then** it shows,
   per test year, the training rows, purged rows and test rows.
2. **Given** each level, **When** it is scored, **Then** each test year shows the log loss of each
   of the three chances and their mean (deciding), the Brier score of each chance next to the
   base rate's, and, for the ranking, the rank correlation of the level's score with the move.
3. **Given** the comparison table, **When** the reader looks for the choice, **Then** it names the
   level, shows each level's yearly scores and its yearly leads over the simpler levels with their
   standard errors, and explains why the chosen level is the simplest within one standard error
   of the best.
4. **Given** a chosen level that does not clearly beat the rule in every test year, **When** the
   findings are written, **Then** they say so plainly and recommend the rule rather than the
   model.

---

### User Story 2 - Honest chances in five bands (Priority: P2)

The chosen level's chances are calibrated on earlier years only and its releases grouped into five
bands. For each band and test year the notebook shows the forecast chances and the real share of
moves above 5%, 10% and 20%, and the band's median move, so the app can say "releases in this band
moved more than 10% in X% of cases".

**Why this priority**: the product never shows a bare number (D47, D62); bands with hit rates are
what the user actually sees.

**Independent Test**: from the chosen level's test-year forecasts, the band table and a calibration
chart per event can be produced and read on their own.

**Acceptance Scenarios**:

1. **Given** the chosen level, **When** calibration is applied, **Then** it is fitted only on
   releases whose moves were known before the period it is judged on, never on the test year.
2. **Given** any release, **When** its three chances are read, **Then** they never contradict each
   other: the chance above 20% is at most the chance above 10%, which is at most the chance above
   5%.
3. **Given** the five bands, **When** the reader compares them, **Then** the real share above 10%
   and the median move rise from the lowest to the highest band in every test year, and each
   band's forecast and real rates are shown side by side.

---

### User Story 3 - Understand what the model uses and judge the hypotheses (Priority: P3)

The notebook shows which features the chosen level relies on, checks that none leaks the answer,
and ends with a verdict on each results-move hypothesis of `docs/hypotheses.md` (H-R1 to H-R6):
a family check (refit without the family, five seeds, every test year) and a direction check (the
expected sign in at least three of the four test years).

**Why this priority**: the researcher must be able to trust and explain the forecast; a leak would
make every number meaningless; the verdicts are the report's claims.

**Independent Test**: the importance table, the family checks and the verdict table can be read
without the rest of the notebook.

**Acceptance Scenarios**:

1. **Given** the chosen level, **When** its strongest features are listed, **Then** each is known
   at the release's `as_of` close, and none of the answer, its dates, identifiers, flags or
   `cum_split_after` appears among the inputs.
2. **Given** each hypothesis family, **When** it is removed and the level refitted, **Then** the
   change in the deciding measure is shown with its spread over five seeds and the verdict
   (supported, not supported, opposite) follows the rule written in `docs/hypotheses.md`.

---

### User Story 4 - A model ready for the one holdout test (Priority: P4)

The chosen model is saved as one frozen object that the guarded holdout command (feature 010) can
score without the notebook. A dry run on the 2023-and-later feature rows (which carry no answers)
proves it scores them without error.

**Why this priority**: the holdout test runs once, on 16 November; a model that cannot be scored
then has no test result.

**Independent Test**: load the saved object in a fresh session and score the 2023+ results-eve
feature rows.

**Acceptance Scenarios**:

1. **Given** the saved object, **When** it is loaded, **Then** it holds its feature list (selected
   by name), all preprocessing, the eligibility flag, the seed, the git commit, the export date
   and the cutoff of every fitted step.
2. **Given** the 2023+ feature rows, **When** the dry run scores them, **Then** every eligible row
   gets three chances and a band, and no move for those years is computed or read (so
   `prev4_mean` and `n_prev` are absent there and the model handles them as missing).
3. **Given** two runs from the same commit and export, **When** their predictions are compared,
   **Then** they are identical.

### Edge Cases

- **A company's first release** (`n_prev` 0, no `prev4_mean`; 1,346 rows): every level still gives
  three chances (the rule falls back to the sector or overall typical move; the models see a "was
  missing" indicator).
- **Moves of zero** (a handful of rows): any log of the move uses a fixed small floor, so it is
  always finite.
- **Extreme ratios and the missing financials of 2010–2011**: cut at the 1st and 99th percentiles
  of each fit's training rows; missing values filled from the training rows with "was missing"
  indicators; never using the test year's values.
- **Long windows** (8-K filed 5 or more days after the release): kept; the test years are also
  reported without them (D60, EDA).
- **The 2020 test year** (the pandemic) is hard for every level; the year-by-year rule (V2-50)
  compares levels within each year so it does not count as doubt.
- **The 20% event is rare** (4% of releases, about 500 per test year): its log loss and band rates
  are shown with their counts; a band with too few cases is flagged, not hidden.
- **A company appears in many releases over time**: releases are never split at random; every
  split is by date.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The model MUST learn and be tested only on releases with `eligible` true and `move`
  present, dated 2022 or earlier, read through the project's development-row loader.
- **FR-002**: The model MUST NOT use as inputs `move`, `close_after`, `filing_date`,
  `report_date`, `cik`, `as_of`, any eligibility, coverage or row-type flag, `cum_split_after`
  (look-ahead), `sector` (the current SIC's sector, not point-in-time) or the three release-timing
  features `days_since_results`, `days_to_next_results` and `months_since_report` (they mean
  something else on any day but a release eve, V2-54, 9 Nov). `prev4_mean` and `n_prev` ARE
  allowed inputs (declared here).
- **FR-003**: The model MUST NOT read the private reference copies (`data/exports/reference/`) or
  compute or read any move whose window starts in 2023 or later.
- **FR-004**: Every evaluation MUST be walk-forward by date: for each test year 2019–2022, learn
  only from releases whose moves were known (`close_after`) before the period judged, with the
  purge counted and shown. No random split anywhere, including inside training for tuning. The
  folds MUST come from `eda.folds` and pass `eda.check_folds`: inner rows for the models, the
  validation year for settings, calibration and band edges.
- **FR-005**: Four levels MUST be built and scored, each giving the three chances: (0) the naive
  baseline `prev4_mean` turned into chances on earlier years only, with the constant base rates
  shown beside it as a floor; (1) a rule (at least the EDA's: the company's typical past move,
  shrunk toward its sector's when it has few releases, combined with recent volatility); (2) a
  classic model; (3) LightGBM.
- **FR-006**: The deciding measure MUST be the mean log loss of the three chances (V2-41); each
  chance's log loss and Brier score (beside the base rate's), and the rank correlation of each
  level's score with the move, MUST be reported for every test year.
- **FR-007**: The chosen level MUST be the simplest within one standard error of the best on the
  deciding measure, the standard error being that of the four yearly differences from the best
  level (V2-50), with each level's yearly scores and leads shown and the reasoning written out.
- **FR-008**: Model-side cleaning (V2-33) MUST be fitted on each fit's training rows only: extreme
  ratios cut at the 1st/99th percentiles, missing values filled from the training rows plus "was
  missing" indicators, one feature of each highly redundant pair in the classic model.
- **FR-009**: Settings MUST be chosen by time-ordered validation inside the training years, never
  on the test year; no early stopping inside a fit: the number of trees is chosen by predicting
  the validation year (V2-49).
- **FR-010**: The three chances MUST be calibrated on earlier years only and never contradict each
  other (above 20% ≤ above 10% ≤ above 5%) for any release.
- **FR-011**: Releases MUST be grouped into five bands ordered by the chance of a move above 10%
  (V2-53, 9 Nov), with band edges set on earlier years only; each band shows, per test year, its
  count, its forecast and real shares above 5%, 10% and 20%, and its median move.
- **FR-012**: The notebook MUST include D60's and the EDA's checks: training from 2012 against
  2010; the test years with and without windows of 5 days or more.
- **FR-013**: The notebook MUST show the chosen level's strongest features and end with a verdict
  on each hypothesis H-R1 to H-R6 (V2-46): a family check on the chosen level (five seeds, every
  test year) and a direction check per test year.
- **FR-014**: Each run MUST be logged with its settings, results, git commit and data (export)
  version, with fixed seeds so that two runs give identical predictions.
- **FR-015**: Every fitted step (each model, calibration and set of band edges) MUST be a
  `sentinel.models.dated.Dated` (V2-49): it learns only from releases whose moves were known
  before its cutoff and refuses to forecast rows dated before it.
- **FR-016**: The chosen model MUST be saved as one frozen object with its feature list, all
  preprocessing, the eligibility flag, seed, commit and export date, plus one scoring function
  taking the model and feature rows; a dry run on the 2023+ results-eve feature rows MUST
  succeed without any 2023+ move.
- **FR-017**: The notebook MUST run start to finish by one command under the memory cap and MUST
  be committed without outputs; written findings MUST quote aggregates only.
- **FR-018**: The notebook MUST end with plain-language findings: the chosen level and why, its
  skill per test year against the baseline and the rule, the bands and their hit rates, the
  hypothesis verdicts, what moves to `src/sentinel/models/`, and open questions.
- **FR-019**: After the researcher approves the level, the model's code MUST move into
  `src/sentinel/models/` with tests, replacing Gemini's `results_move.py`, and the notebook MUST
  then use that code and give the same numbers.

### Key Entities

- **Release row**: a company's results announcement with its features at `as_of`, `prev4_mean`,
  `n_prev`, its eligibility flag and its answer (`move`, known at `close_after`).
- **Fold**: one test year (2019–2022) with its inner training rows, validation year and purge.
- **Level**: one way of forecasting the three chances, with its scores per fold.
- **Band**: one of five groups of releases by forecast, with its real hit rates and median move
  per test year.
- **Frozen model**: the chosen level as one saved object with everything needed to score new rows.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The notebook runs start to finish from a fresh clone plus the private export by one
  command, under the 5 GB memory cap, without errors.
- **SC-002**: Two runs from the same commit and export give identical predictions for every
  release.
- **SC-003**: Every level is reported for all four test years with every measure; the chosen level
  is named with its reasoning.
- **SC-004**: The chosen level's mean log loss beats the constant base rates in every test year; if
  it does not also clearly beat the rule in every test year, the findings recommend the rule.
- **SC-005**: Across the five bands the real share above 10% and the median move rise from the
  lowest to the highest band in every test year.
- **SC-006**: For 100% of releases the three chances are in order (above 20% ≤ above 10% ≤ above
  5%).
- **SC-007**: The frozen model scores 100% of the eligible 2023+ results-eve feature rows in the
  dry run, and no 2023+ move is computed or read.
- **SC-008**: The researcher approves the chosen level after reading the executed notebook.

## Assumptions

- The export of 9 November 2026 (`data/exports/ml/results_move.parquet`, cleaning V2-22 to V2-32,
  with V2-44 and V2-45) is the data of record; a later export means re-running the notebook.
- The deciding measure is fixed (V2-41); the rank correlation and absolute errors of Gemini's
  version are reported only as context.
- The classic model is a regularised regression or logistic regression; the trees are LightGBM,
  both already in the project. Whether a level forecasts the move's size and derives the three
  chances from it, or forecasts each chance directly, is chosen in the plan and on validation
  years, never on the test years.
- Run logging uses MLflow, already a project dependency.
- Daily scores (009) of the results move need `prev4_mean` from moves after 2022, which are sealed
  until the holdout test (010); until then the daily score treats it as missing or is not shown.
  The holdout test itself computes the 2023+ moves, and with them `prev4_mean`, inside its guarded
  command.
- Gemini's `plan.md`, `research.md`, `data-model.md`, `tasks.md` and `contracts/` in this folder
  predate the audit and are rewritten by the plan and tasks steps.
- Out of scope: changing the pre-registered definition, the daily scoring (009), the report (008),
  the app (011–018) and the holdout test itself (010).
