# Feature Specification: Validation round on named cases

**Feature Branch**: `022-validation`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "Start the validation round now" (V2-25 in docs/decisions.md): check
values that look normal but may be wrong, against the SEC filings and Yahoo, for named companies,
before the models (005–007) are built.

## Context

The EDA (004) found and fixed what statistics can show (V2-22 to V2-24). A wrong value that looks
plausible needs a check against the source. Seven kinds of doubt remain, each with a measured size
on the 30 October build:

| # | Doubt | Size |
|---|---|---|
| 1 | Yahoo and Tiingo disagree on daily returns | 194 companies |
| 2 | One-month returns above +1,000% at prices of \$1 or more: real, or a missing split? | 54 rows |
| 3 | A stock split inside a dilution window: real dilution, or a split read as one? | 6,780 rows dilute 25% vs 9.5% |
| 4 | A company's first share count 100× away from its next ones (the typo rule cannot see a first count) | 151 companies |
| 5 | Five or more results releases in a year: duplicates? | 111 company-years |
| 6 | A Tiingo series whose price jumps far from its own level (CLS Holdings \$144,200) | 47 series |
| 7 | Insider lines over \$1 billion with no market price to judge them | 2,304 lines, 723 companies |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Know whether each doubt is a real problem (Priority: P1)

The researcher opens the validation notebook and reads, for each of the seven checks: what was
checked and why, how many rows and companies it concerns (overall and in the eligible training
rows), a sorting of the cases into causes, named examples compared with their source, and a
verdict: no problem, a problem with a proposed rule, or needs a decision.

**Why this priority**: the models start next; an error found after training means training again.

**Independent Test**: the notebook runs start to finish with one command and ends with a verdict
table covering all seven checks.

**Acceptance Scenarios**:

1. **Given** the build of 30 October, **When** the notebook runs, **Then** each check shows its
   size, its causes and at least three named cases with their evidence.
2. **Given** a named case, **When** the reader looks at it, **Then** the notebook shows the
   source it was compared with (an SEC filing's text and link, or the other price source).

### User Story 2 - Turn real problems into decided rules (Priority: P1)

Each real problem becomes a proposal in `docs/decisions.md` (what, why, rows affected, a named
example). The researcher decides; accepted rules go into the pipeline with tests, applying to every
year alike and only to what was known at the time (constitution I).

**Independent Test**: every "problem" verdict has a proposal entry with counts; every accepted
rule has a test that fails without it.

**Acceptance Scenarios**:

1. **Given** an accepted rule, **When** the pipeline is rebuilt, **Then** the check that found the
   problem shows it resolved, and the unit tests and the EDA notebooks still run.

### Edge Cases

- A source document cannot be fetched (removed, renamed): the case is marked "not checkable" with
  the reason, never guessed.
- Both sources agree but are both wrong: out of reach without a third source; named cases use the
  SEC filing as the third source where it holds the number (share counts, splits, releases).
- A check that needs future information to diagnose (for example "the next counts disagree with the
  first") may be used to *find* problems, but any rule proposed from it must work point-in-time.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: One notebook, `notebooks/022-validation.ipynb`, with one section per check (1–7), each
  saying what is checked and why, its size (all rows and eligible training rows), the causes, at
  least three named cases with evidence, and a verdict.
- **FR-002**: Evidence from SEC filings is fetched live (with the contact from `.env`, under 10
  requests a second) and shown as a short excerpt with the document's link; nothing is written to
  `data/`.
- **FR-003**: The notebook ends with a verdict table (check, verdict, rows and companies affected,
  proposed rule or decision needed) and a findings section in plain words.
- **FR-004**: Each proposed rule is logged in `docs/decisions.md` as a proposal for the researcher.
- **FR-005**: Accepted rules are implemented in `src/sentinel/` with unit tests, point-in-time;
  then rebuild under the memory cap, re-run the EDA notebooks and update their findings.
- **FR-006**: Reusable checks live in `src/sentinel/validation.py` with unit tests on synthetic data.
- **FR-007**: Outputs are not committed; written findings quote aggregates and named public
  facts (a company's split, its filed share count), never Tiingo price series.

### Key Entities

- **Check**: one of the seven doubts, with its query, size and verdict.
- **Named case**: a company and date picked to show a cause, with its evidence and verdict.
- **Proposal**: a rule for the researcher, with counts and a named example.

## Success Criteria *(mandatory)*

- **SC-001**: All seven checks have a verdict; at least 20 named cases are checked in total.
- **SC-002**: The notebook runs start to finish with one command in under 10 minutes within the
  memory cap.
- **SC-003**: Every proposal names the rows and companies it affects.
- **SC-004**: After accepted rules are implemented, the tests pass and the EDA notebooks run.

## Assumptions

- The build of 30 October 2026 (after V2-22 to V2-24, V2-26, V2-27) is the data checked.
- SEC EDGAR is reachable; Yahoo is the only free check for prices beyond Tiingo.
- The verdicts are the agent's reading of the evidence, shown so the researcher can check them.
