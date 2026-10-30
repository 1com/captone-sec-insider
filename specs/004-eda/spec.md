# Feature Specification: EDA and data-quality report

**Feature Branch**: `004-eda`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "Create EDA notebooks for each ML dataset separately. Do a full EDA and
present the findings at the end of each notebook, for each dataset." (Roadmap feature 004, issue
#76: explore the development rows of the three training sets, find data-quality problems and
cleaning rules, and give modelling advice for 005, 006 and 007. The researcher asked the coding
agent to do it; docs/plan.md listed the teammate as owner.)

## Context

The data platform writes three training sets to `data/exports/ml/`, one per risk question:

| Question | File | One row is | Answer | Naive baseline |
|---|---|---|---|---|
| Volatility (005) | `volatility.parquet` | a company at a month end, 2012 – Sep 2022 | `vol_63_future`: volatility over the next 63 sessions, annualised | `vol_63`, the past 63 sessions |
| Results-day move (006) | `results_move.parquet` | a company on the eve of a results release, 2010 – 2022 | `move`: the market-adjusted absolute move on results day | `prev4_mean`, the mean of the previous four moves |
| Dilution (007) | `dilution.parquet` | a company at a month end, 2012 – Jun 2022 | `dilution`: shares outstanding up 10% or more within 182 days | the base rate (about 10%) |

Each has about 100 features (price, size, financial ratios, filing events, insider activity, short
volume, macro) plus identifiers, coverage flags, `eligible` and the answer. Nobody has looked at
them as a whole yet. The models (005–007) start next week and need to know what is in the data,
what is wrong with it and what to watch for.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Understand the volatility training set (Priority: P1)

The researcher (or the teammate who builds the volatility model) opens the volatility notebook,
runs it from top to bottom, and reads: how many rows and companies there are per year, sector, size
and filer type; which rows are eligible and why others are not; which features are missing and
why; the answer's distribution; how well the naive baseline already does; which features relate to
the answer and whether those relations hold over the years; any leakage; and, at the end, a
written findings section with cleaning rules and modelling advice.

**Why this priority**: volatility is the first model (005, 4–5 November) and leads the stock page.

**Independent Test**: run the volatility notebook alone with one command; it finishes without
errors and ends with its findings.

**Acceptance Scenarios**:

1. **Given** the current export, **When** the notebook is run start to finish, **Then** it
   completes and every section shows its tables and charts.
2. **Given** the notebook's findings, **When** the reader looks for the baseline's skill, **Then**
   they find the baseline's error on the development years and on the test years 2019–2022.
3. **Given** a feature that is missing for many rows, **When** the reader looks it up in the
   missing-value section, **Then** the notebook states why it is missing (for example: no
   financial filings for a foreign filer, not enough price history).

---

### User Story 2 - Understand the results-day move training set (Priority: P2)

The same for the results-day move: one row per results release; the answer's distribution (it is
an absolute move, so heavily skewed); how many releases have fewer than four earlier moves; how
well the mean of the previous moves predicts the next; the timing (eve, release, close after) and
whether any feature uses information from after the eve.

**Why this priority**: the second model (006, 6–9 November).

**Independent Test**: run the results-move notebook alone; it completes and ends with its findings.

**Acceptance Scenarios**:

1. **Given** the export, **When** the notebook runs, **Then** it reports rows per year, the share
   with a usable baseline (`n_prev`), and the baseline's error.
2. **Given** the leakage checks, **When** the reader reads them, **Then** every feature has been
   checked against the release date and none is dated after the eve, or the exceptions are listed.

---

### User Story 3 - Understand the dilution training set (Priority: P3)

The same for dilution: a yes/no answer that is true about 10% of the time; the base rate by year,
sector, size and filer type; how the obvious signals (cash runway, recent offerings, share growth,
loss-making) separate the two groups; and whether the answer can be wrong because of share-count
data problems (splits, share-class changes, missing counts).

**Why this priority**: the third model (007, 10–11 November); it also feeds the standalone
dilution check page.

**Independent Test**: run the dilution notebook alone; it completes and ends with its findings.

**Acceptance Scenarios**:

1. **Given** the export, **When** the notebook runs, **Then** it shows the base rate overall and by
   year, sector and size, and how much the strongest single features lift it.
2. **Given** a share-count jump caused by a split rather than an issue of new shares, **When** the
   reader reads the outlier section, **Then** the notebook shows whether such cases are in the
   answer and how many.

---

### User Story 4 - Turn findings into pipeline rules (Priority: P2)

Where a notebook finds a data problem that should be fixed for every row, the fix is not done in
the notebook. It is written down as a proposed cleaning rule (what, why, how many rows) so it can
be logged in `docs/decisions.md` and implemented in the pipeline with tests, applying to every year
alike, holdout included.

**Why this priority**: a fix made only in a notebook would make the model's training data differ
from the data it scores each day.

**Independent Test**: each proposed rule in the findings names the rows it affects and the count.

**Acceptance Scenarios**:

1. **Given** a finding that needs a cleaning rule, **When** the findings are written, **Then** the
   rule is stated with its reason and affected row count, and listed for `docs/decisions.md`.

### Edge Cases

- **Holdout rows.** Rows from 2023 on have no answers in the training sets; the notebooks never
  load answers for them and never explore the private reference copies (002).
- **Ineligible rows.** They are described (how many and why) but every relation to the answer is
  measured on eligible rows with an answer, as the models will use.
- **Very skewed values.** Market value, traded value, ratios and the answers have long tails;
  summaries use medians, percentiles and logs where the mean would mislead.
- **Many rows per company.** Month-end rows of one company are not independent; counts are given
  both in rows and in companies, and relations are also checked per year.
- **Machine memory.** The largest file has about 734,000 rows and 110 columns; each notebook must
  run within the 5 GB memory cap of this machine.
- **Public repository.** The notebooks are committed without outputs; their written findings quote
  only aggregates (counts, shares, medians, correlations), never a single company's prices or
  returns (Tiingo terms).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: There MUST be one notebook per training set: volatility, results-day move, dilution.
- **FR-002**: Each notebook MUST read only its training file from the private export and MUST use
  only development rows (as of 2022 or earlier); it MUST NOT read answers for 2023 or later.
- **FR-003**: Each notebook MUST show the file's shape, columns grouped by family (identifiers,
  flags, price, size, financials, filing events, insider, short volume, macro, answer), and data
  types.
- **FR-004**: Each notebook MUST show coverage: rows and companies per year, by sector, by size
  band, by filer type and coverage level; and the eligible share and the reasons rows are not
  eligible.
- **FR-005**: Each notebook MUST show, per feature, the share of missing values overall and by
  year, and give the reason for each large gap.
- **FR-006**: Each notebook MUST list impossible or extreme values (negative where impossible,
  infinite, beyond plausible limits) with counts.
- **FR-007**: Each notebook MUST describe the answer: its distribution, its level by year, sector
  and size, and (dilution) the base rate.
- **FR-008**: Each notebook MUST measure the naive baseline on the eligible rows with answers,
  overall and per test year 2019–2022, with the error measure the model feature will use.
- **FR-009**: Each notebook MUST show each feature's relation to the answer (rank correlation; the
  answer by feature decile for the strongest), and whether the strongest relations hold in each
  year.
- **FR-010**: Each notebook MUST show which features are near-duplicates of each other (high
  correlation between features).
- **FR-011**: Each notebook MUST check for leakage: no feature relates to the answer implausibly
  well, the answer's window end lies after the row date, and the purge rule (training rows whose
  window ends after a test year starts are dropped) leaves enough rows in each training set.
- **FR-012**: Each notebook MUST end with a written Findings section: what is clean, what needs a
  cleaning rule (what, why, rows affected), and advice for the model (transforms, features to drop
  or group, the error measure, what to watch).
- **FR-013**: Each notebook MUST run start to finish with one command, deterministically (fixed
  seeds for any sampling), within the 5 GB memory cap, and MUST NOT write to `data/`.
- **FR-014**: The notebooks MUST be committed without outputs.
- **FR-015**: Proposed cleaning rules MUST be listed so they can be logged in `docs/decisions.md`;
  implementing them in the pipeline is a separate change with its own tests.

### Key Entities

- **Training set**: one Parquet file per question; rows are company × date; features first, the
  answer last; `eligible` marks the rows models may learn from.
- **Development rows**: rows dated 2022 or earlier with an answer; the test years 2019–2022 are
  part of them.
- **Finding**: a stated fact about a training set with its evidence (a count, a share, a chart) and,
  where needed, a proposed cleaning rule or a modelling advice.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Each of the three notebooks runs start to finish with one command in under 10 minutes
  on this machine, within the 5 GB memory cap, and gives the same tables on a second run.
- **SC-002**: Every one of the about 100 features of each set appears in the missing-value table
  and the feature–answer table.
- **SC-003**: Each notebook's Findings section states the baseline's skill, the 5–10 strongest
  features, every proposed cleaning rule with its affected row count, and modelling advice.
- **SC-004**: The researcher, who is new to markets, can read each Findings section without
  looking up terms: each term is explained where it is first used.
- **SC-005**: No committed notebook contains an output cell.

## Assumptions

- The export is the one written by the 30 October update; features and answers are as defined in
  `src/sentinel/features/`, `src/sentinel/labels/risk.py` and `config/risk_params.yaml` v5.
- The error measures follow D60 and `config/risk_params.yaml` v5 (read in the plan); the EDA
  reports them but does not pick a model.
- The notebooks are exploration (docs/plan.md, "Notebooks and code"); reports that must regenerate
  by command are 008's. The written findings are the deliverable here.
- The teammate may extend these notebooks; ownership in docs/plan.md is updated to the coding
  agent with the researcher.
- Feature 003 (nbstripout and the CI check) is not built yet; until then outputs are stripped
  before each commit by command.
