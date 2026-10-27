# Feature Specification: Training Data (Labels, Features, ML Dataset)

**Feature Branch**: `006-training-data`

**Created**: 2026-10-26

**Status**: Draft

**Input**: User description: "Feature 006 — the training data, finalised this week (researcher, 26 October 2026). docs/initialplan.md Steps 11, 12 and 14: development labels (§6.6 four measures at five horizons, gross and net of cost, delisting returns §6.7, windows ending by 31 December 2022), features F1–F29 as of T (§7.2), and the ML dataset (§7.2: clusters only, fixed preprocessing, four purged walk-forward folds with fit, tuning and calibration slices, calendar-concurrency weights, fold-size rule). Constitution I, III, IV, V, VI. No post-event return may be computed on the real data before prereg-v1: code and tests are written first on synthetic data, and the commands refuse to run until the tag exists. Out of scope: the event study (Step 13), models (Steps 15–17), the holdout job (Step 18)."

## Context

Features 002 and 004 built the events, prices, costs and delistings. This feature turns them into the table the models train on: one row per development cluster with its 29 features, its label and its fold. The method is pre-registered; [research.md](research.md) records the details the plan leaves open, decided before the lock as D53.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Labels for every development event (Priority: P1)

The researcher has, for every priced event from 2012 whose window ends by 31 December 2022, its abnormal return over 5, 21, 63, 126 and 252 sessions against SPY, IWM, its industry (equal- and value-weighted) and the FF5 + momentum model, gross and net of cost, with delistings handled.

**Why this priority**: the target of every model and the outcome of the event study (Step 13).

**Independent Test**: synthetic price paths with known returns, a mid-window delisting of each class, a missing entry open and an event whose window crosses 31 December 2022; values match hand calculations.

**Acceptance Scenarios**:

1. **Given** a stock up 10% from the open of T+1 to the close of T+63 and its industry up 4%, **When** labels are built, **Then** the 63-session industry BHAR is 0.06 and net = 0.06 − cost.
2. **Given** a stock whose prices end at T+30 with class performance on Nasdaq, **When** labels are built, **Then** the −55% delisting return applies and the benchmark is earned afterwards; the 0% and −100% bounds are stored.
3. **Given** an event whose 252-session window ends in 2023, **When** labels are built, **Then** that horizon has no row while its 63-session window (ending in 2022) does.
4. **Given** no `prereg-v1` tag, **When** `sentinel labels` runs on the real warehouse, **Then** it exits 7 without writing.

### User Story 2 - Features as of T (Priority: P1)

Every development event has F1–F29, each computed only from filings on or before T and prices up to the last session on or before T.

**Why this priority**: the model's inputs; the point-in-time rules are non-negotiable (constitution I).

**Independent Test**: a synthetic issuer with purchases, sales, roles, filings and XBRL facts before and after T; features match hand values; deleting every record dated after T changes nothing (truncation test).

**Acceptance Scenarios**:

1. **Given** a cluster of a CEO and two directors, **Then** F1 = 3, F4 = 1, F5 = 2.
2. **Given** an XBRL value first filed the day after T, **Then** the previous period's value is used.
3. **Given** an earlier purchase by a buyer whose 63-session window ends after T, **Then** it does not count in F10.

### User Story 3 - The dataset the models train on (Priority: P1)

One table of development clusters with features, target, folds, slices and weights, versioned.

**Why this priority**: it is what "training data" means for Steps 15–17.

**Independent Test**: synthetic events across 2012–2022: fold membership, purging, weights and the fold-1 rule match hand values; no training window crosses its fold boundary or 31 December 2022.

**Acceptance Scenarios**:

1. **Given** an event signalled in November 2018 whose window ends in February 2019, **Then** it is purged in folds 2019 (it crosses the test year) and 2020 (it reaches the tuning slice), and is in the fit set from fold 2021.
2. **Given** a fit set of 499 events in fold 1, **Then** fold 1 is marked dropped.

### User Story 4 - The same events at every horizon (Priority: P2)

The researcher has the events stacked at 21, 63, 126 and 252 sessions, each purged and weighted by its own window, so one model can learn what happened after each period (D54).

**Independent Test**: synthetic events: each horizon's purging and uniqueness match hand values, and the primary 63-session table is unchanged.

**Acceptance Scenarios**:

1. **Given** a cluster signalled on 15 November 2018, **Then** in the 2019 fold its 21-session window trains and its 63- and 126-session windows are purged.

### Edge Cases

- No usable open at T+1: entry at that day's close, flagged.
- Price gaps inside the window: last close on or before the exit session.
- SIC code in no 49-industry range: industry "Other".
- Fewer than 120 beta days: no CAR; other measures unaffected.
- Missing cost: net and target null, counted.
- Insiders with no holdings before: left out of F7, counted in F8.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Labels MUST follow plan §6.6 and §6.7 and research R2–R7, for every priced A, B1 and B2 event with T from 1 January 2012, only for windows ending by 31 December 2022.
- **FR-002**: Each label row MUST store gross, cost, net, the delisting class used and the 0% and −100% bounds.
- **FR-003**: Features F1–F29 MUST follow plan §7.2 and research R8–R10, using only information public by T.
- **FR-004**: F10 MUST use only purchase windows that ended before T, and only windows ending by 31 December 2022.
- **FR-005**: The ML dataset MUST follow plan §7.2 and research R11.
- **FR-006**: The three commands MUST refuse to run on the real warehouse before `prereg-v1` (research R1).
- **FR-007**: Tables holding Tiingo-derived values MUST be in the Tiingo register.
- **FR-008**: Every step MUST be deterministic and part of the offline rebuild.
- **FR-009**: Development code MUST NOT read or write the `hold` schema.
- **FR-010**: The multi-horizon tables MUST follow research R13; `ml.dataset` MUST stay the pre-registered 63-session table.

### Key Entities

- **Label**: event × horizon × measure: gross, cost, net, bounds, delisting class.
- **Purchase outcome**: clean purchase: 63-session industry BHAR, cost, net.
- **Feature row**: event: F1–F29 and missing-value flags.
- **Dataset row**: development cluster: model-ready features, target, uniqueness; **fold assignment**: fold × event: part (fit, tune, calibrate, test, purged) and weight.

## Success Criteria *(mandatory)*

- **SC-001**: Point-in-time, truncation, fold-boundary and holdout-guard tests pass.
- **SC-002**: 10 labels recomputed by hand by the researcher match (task 4.2).
- **SC-003**: Every development cluster with a cost has a target; the counts of events without one are reported by reason.
- **SC-004**: Post-floor counts and effective sample sizes per fold are reported before any model is fitted.
- **SC-005**: The offline rebuild reproduces the new tables exactly.

## Assumptions

- `prereg-v1` is tagged once the researcher approves D45–D53 (task L.2); until then only synthetic data is used.
- The event study (Step 13) is written up and approved before any model is fitted; the dataset itself is not a model result.
