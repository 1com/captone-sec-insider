# Feature Specification: The holdout test

**Feature Branch**: `010-holdout-test`

**Created**: 2026-11-10

**Status**: First version

**Input**: User description: "Feature 010 · Risk holdout test (roadmap 010, issue #69): the one test
of the three approved models on the answers from 2023 on, sealed until now: a guarded command the
researcher runs once on 16 November. It refuses unless the models are frozen and no earlier run
exists; it computes the 2023+ answers with the development label code and a later end date, scores
the frozen models and their baselines, records the results for the model report (008) and a log
entry; a second run is refused."

## Context

Every choice in the three models (005, 006, 007) was made on the development years: walk-forward
test years 2019–2022, with answers whose windows end by 31 December 2022. Choosing a model by
looking at those test years flatters it a little. The **holdout** answers the only question that
matters in the end: do the chosen models work on data nobody looked at while choosing them? It is
pre-registered (D60, `config/risk_params.yaml`: "Rows signalled from 2023 form a sealed risk
holdout, labelled and evaluated once at the end") and protected by the constitution (IV: the
holdout "MUST NOT be computed by any development step and MUST be evaluated exactly once, by a
guarded and logged run").

What is already true: the pipeline never computes an answer for a window ending after 2022 (the
label code stops at `development.last_window_end`); no notebook or model reads the private
reference copies; the 2023+ feature rows have the training files' columns in the same order and
types (checked 30 Oct); each frozen model passed a dry run on them without answers; the three
approved models are packaged (`src/sentinel/models/`) and their frozen objects are recorded in
MLflow with the git commit and the data hash; the model report shows a holdout section that reads
"not run yet" until this feature's records exist (008, contract in
`specs/008-model-report/contracts/report-record.md`).

**The three answers from 2023 on**, computed by the same label functions as development with only
the end date moved to the run day:

| Question | Rows | Answer known |
|---|---|---|
| Dilution | month ends from January 2023 | 182 days later: rows up to about May 2026 |
| Results-day move | results releases from January 2023 | the close after the 8-K: releases up to the run day |
| Volatility | month ends from January 2023 | 63 sessions later: rows up to about August 2026 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The researcher runs the one holdout test (Priority: P1)

On 16 November the researcher runs one command. It checks that everything is in place, computes
the sealed answers from 2023 on, scores each frozen model and its baselines on them, records the
results where the model report reads them, writes a log entry, and prints a short summary per
question. The results then go into the report as they came out; no model changes afterwards.

**Why this priority**: this is the test the whole method was built to protect; it can be run once.

**Independent Test**: on a synthetic database and MLflow store, the command runs, records one
result per question and a log entry; the model report then shows them.

**Acceptance Scenarios**:

1. **Given** the frozen models, no earlier run and the data of the run day, **When** the researcher
   runs the command, **Then** it records per question the measures of the frozen model and its
   baselines on the 2023+ answers (per calendar year and over all), the bands with what happened in
   them, the volatility range's coverage, and the rows used, and appends one log entry.
2. **Given** the records, **When** `sentinel report` runs, **Then** each question's holdout section
   shows them unedited, with the date.

---

### User Story 2 - The guard (Priority: P1)

The command refuses to run unless the three frozen models are recorded, the registration lock
holds and no earlier holdout run exists; a second run is always refused, with no way around it. A
check mode verifies everything except the answers, so it can be run safely before 16 November.

**Why this priority**: a test that can be repeated is not a holdout test; the log is the proof that
it ran once.

**Independent Test**: with a recorded run present, the command refuses and changes nothing; in
check mode it reports the rows it would use and computes no answer.

**Acceptance Scenarios**:

1. **Given** a missing frozen model, a changed `config/risk_params.yaml` or an earlier run, **When**
   the command runs, **Then** it refuses with the reason and writes nothing.
2. **Given** the check mode, **When** it runs, **Then** it lists the frozen models it would test and
   the 2023+ feature rows per question, and no 2023+ answer is computed or written anywhere.

---

### User Story 3 - The same rule for the answers (Priority: P2)

A test shows that the label functions with a later end date give exactly the development answers
for every row whose window ended by 2022: the holdout answers come from the same rule, only later.

**Why this priority**: the holdout compares like with like only if the answers are defined
identically.

**Independent Test**: on a synthetic panel, the labels with the end date 2022-12-31 and with a
later end date agree on every row whose window ended by 2022.

**Acceptance Scenarios**:

1. **Given** a synthetic panel, **When** the answers are computed with two end dates, **Then** the
   rows of the earlier end date are identical in both.

### Edge Cases

- **Rows dated in late 2022 whose windows end in 2023** belong to neither the development nor the
  holdout: left out (as the purge leaves them out of the test years).
- **The newest rows** whose windows have not closed by the run day have no answer: left out, counted.
- **Dilution's split-like "yes" answers** (a stock split read as dilution) are dropped from the
  2023+ answers by the same rule as in development (V2-39, V2-40).
- **Volatility answers of exactly 0** have no logarithm: left out, counted (as in development).
- **The results-day move's history** (`prev4_mean`, `n_prev`) for 2023+ releases comes from the same
  label code, which includes the earlier 2023+ moves (known by each release's date).
- **The daily update** writes the database at 10:00 on weekdays: the command reads it read-only and
  is not run at the same time.
- **Aggregates only** in the records and the summary.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: One command (`sentinel holdout`) MUST run the test; `sentinel holdout --check` MUST
  check everything except the answers.
- **FR-002**: The command MUST refuse unless: the frozen models of the three questions are
  available as [NEEDS CLARIFICATION: which frozen models are tested: the objects the approved
  notebooks froze and recorded in MLflow on the export of 9 November, or the same models retrained
  with `sentinel train` on the run day's export?], each with its git commit and data hash; the
  registration lock holds (`config/risk_params.yaml` equals its `prereg-risk-v5` version); and no
  earlier holdout run exists (no record in experiment `010-holdout` and no log entry).
- **FR-003**: A second run MUST be refused, whatever the options; nothing may delete or override
  the log from the command.
- **FR-004**: The 2023+ answers MUST be computed by the development label functions with the end
  date moved to the newest session in the data, in memory only: never written to the label tables,
  the exports or any file other than the records.
- **FR-005**: The rows MUST be the feature rows dated 1 January 2023 or later with the question's
  eligibility and an answer, joined as the training files are; volatility answers of 0 and
  dilution's split-like answers dropped by the development rules; the rows left out counted.
- **FR-006**: Each frozen model MUST be scored through its own `predict` function, unchanged.
- **FR-007**: Beside each model the command MUST score [NEEDS CLARIFICATION: which simpler levels:
  the pre-registered naive baseline only (with the base rates as the floor), or also the rule
  level?], each made for the holdout exactly as for a test year (learning only from answers known
  before 2023).
- **FR-008**: The measures MUST be those of the test years (the deciding measure first), per
  calendar year from 2023 and over all years; with the bands and what happened in them, and the
  volatility range's coverage.
- **FR-009**: The results MUST be recorded per question in experiment `010-holdout` as the 008
  contract defines (`holdout.json`), with the run date, the models' provenance and the data hash;
  and one log entry MUST be appended to a log in the repository's data folder.
- **FR-010**: The check mode MUST compute no answer and write nothing but its printed summary.
- **FR-011**: Unit tests MUST show: the guard refuses (missing model, changed parameters, earlier
  run); the check mode computes no answer; the label functions with a later end date reproduce the
  development answers exactly; the records follow the 008 contract and `sentinel report` shows them.
- **FR-012**: The command MUST run under the memory cap with a read-only connection to the build
  database.

### Key Entities

- **Frozen model**: one per question, with its provenance (commit, data hash, cutoffs).
- **Holdout rows**: the 2023+ feature rows with their answers (in memory only).
- **Holdout record**: one MLflow run per question (008 contract).
- **Holdout log**: an append-only list of runs; one entry is the proof of a single run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A second run is refused and changes nothing.
- **SC-002**: Before 16 November the check mode passes, and no 2023+ answer exists in any table,
  export, record or file.
- **SC-003**: The label functions with a later end date reproduce 100% of the development answers.
- **SC-004**: After the run, the report's holdout sections show the recorded numbers unedited.
- **SC-005**: The run finishes under the memory cap in under 20 minutes.

## Assumptions

- The researcher runs the command on 16 November 2026, with the data current to that day and the
  daily update not running at the same time.
- The decision log records the run and its date; the results are not acted on before the report
  (019) and no model is changed afterwards (constitution IV); later refits (021) may use the 2023+
  answers, as a logged step.
- Out of scope: the daily scores and live outcomes (009), the app (011–018).
