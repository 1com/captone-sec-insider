# Feature Specification: Price history repair, then retrain and test

**Feature Branch**: `027-price-history-repair`

**Created**: 2026-11-11

**Status**: Draft

**Input**: User description: "Repair how prices are matched to companies over time, then retrain the
three models and run the holdout test" (the researcher, 11 Nov 2026: option C of three, decision
V2-65). The audit of 11 November (read-only, every company) found that a company's price history
is often cut or mixed, not by bad prices but by the rules that decide which company a ticker's
prices belong to and from when. Evidence (7,351 listed companies, 7,038 of them priced):

| Problem | Companies | Example |
|---|---|---|
| A ticker change drops everything before it (one ticker per company) | 370 listed; 152 disappeared whose prices stop over a year before their last report | MGP Ingredients (MGPI → CASK, 5 Nov 2026): 2 days kept of 16 years, though the raw files hold MGPI's whole history; Viavi (JDSU), Ingersoll Rand (Gardner Denver, GDI), Xcerra (LTXC → XCRA), Hanger (HGR → HNGR) |
| History cut at the start of the ticker's "current listing" in Tiingo's list, which also marks exchange moves and where Tiingo's coverage of small stocks begins | 943 with stored prices dropped; 84 exchange moves; 109 whose own insider filings used the ticker over a year before the cut | Palatin (NYSE American 1997–2025, then Nasdaq: 15 years cut); cut days 4 Jan 2016 (60), 22–26 Sep 2017 (53) |
| History cut by another company's use of the ticker | 219 with stored prices dropped; 67 of them at the same time as the company's own use (a sister company or a typo) | Digital Realty: its operating partnership holds 16 years of DLR prices, the listed company starts on 5 Oct 2026 (V2-63's rule misses a use ending the same day) |
| Two companies glued into one series (a hole of over a year) | 39 listed, 28 disappeared | Standard BioTools (LAB) carries LaBranche's 2010–2011 prices, its own years as Fluidigm (FLDM) missing; Heidmar (HMR) |
| Only the first SEC ticker is tried | 85 listed without prices though another ticker of theirs has a series (mostly foreign ADRs, which need a ratio) | Telephone & Data Systems: no prices; Chatham Lodging priced by its preferred share |
| Disappeared US companies with insider filings and no prices at all | 3,084 (against 3,945 priced) | not yet classified; some never traded |

Effect: the dilution training file holds rows only where prices exist, so it lacks between 24,000
(clear cases) and 63,000 (every cut) company-months of its 714,949 (3–9%), concentrated in companies
that changed ticker or exchange; and its 2012–2022 rows drift as companies change tickers (96 rows
lost between 9 and 10 November).

## Clarifications

### Session 2026-11-11

- Q: When does the holdout test run, given the hand-in (product 17 Nov, report 18 Nov)? → A: By
  Tuesday 17 November if the repair, the rebuild, the retrained models and their approval are all
  done, so the report includes it; never on a partly repaired pipeline or unapproved models: if not
  ready by Monday evening, after the hand-in (before 26 November), the report saying it is to come.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A company that changed its ticker keeps its whole history (Priority: P1)

The researcher (and an app user) opens a company that changed its ticker, for example after a
rename or a merger in which it kept its legal identity, and sees one continuous price history across
its tickers, back to 2010 or its first trading day; the training rows of every year it traded are
present.

**Why this priority**: the largest family (370 listed companies, plus disappeared ones); it removes
whole years of real companies from the training data and makes the training rows drift daily.

**Independent Test**: for MGP Ingredients, Viavi, Ingersoll Rand, Xcerra and Hanger, the history
spans their tickers with no gap at each switch, and each switch's dates and price levels agree.

**Acceptance Scenarios**:

1. **Given** a company whose own filings show ticker A until a day and ticker B from the next,
   **When** its history is built, **Then** it holds A's prices up to the switch and B's after, with
   the switch day recorded.
2. **Given** a switch where the two series do not meet (a gap of weeks, or price levels that
   disagree once splits are allowed for), **When** the history is built, **Then** the join is not
   made, and the audit lists the company with the reason.
3. **Given** a company whose ticker changed today, **When** the daily update runs, **Then** its
   earlier history and training rows are unchanged.

---

### User Story 2 - A history is cut only where another company really held the ticker (Priority: P1)

A company's history is not cut by an exchange move, by the day a provider's coverage begins, or by
a sister company or a typo that used the same ticker at the same time; it is still cut where a
different company held the ticker before.

**Why this priority**: 256 listed companies with clear evidence of a wrong cut (12,162
company-months of 2012–2022), among them large companies (Digital Realty).

**Independent Test**: Palatin and AMN Healthcare start in January 2010; Digital Realty starts in
January 2010 and its operating partnership has no prices of its own; Fabrinet still starts in 2010
(V2-63).

**Acceptance Scenarios**:

1. **Given** a ticker that moved from one exchange to another, **When** the history is built,
   **Then** it runs across the move.
2. **Given** a provider whose records of a small stock begin later than another provider's series,
   **When** no other company used the ticker before, **Then** the longer series is kept.
3. **Given** two companies using a ticker at the same time (a parent and its operating partnership,
   or a typo), **When** the histories are built, **Then** the listed holder keeps the prices and the
   other gets none from that ticker.
4. **Given** a ticker that another company held before and gave up, **When** the history is built,
   **Then** the company's history starts after that company's last use, as now.

---

### User Story 3 - One series never mixes two companies (Priority: P1)

Prices that belonged to another company are never shown or used as a company's own.

**Why this priority**: these rows are wrong, not missing: they give a company another company's
returns and volatility.

**Independent Test**: Standard BioTools holds none of LaBranche's prices and has its years as
Fluidigm (once US1 joins FLDM); Heidmar holds no 2010 block.

**Acceptance Scenarios**:

1. **Given** a series with a hole of more than one year, **When** the company's own evidence does
   not cover the part before the hole, **Then** that part is not the company's.

---

### User Story 4 - Every listed company with a usable series is priced, from its common stock (Priority: P2)

**Why this priority**: few companies, but visible ones (Telephone & Data Systems has no prices).

**Independent Test**: Telephone & Data Systems is priced as TDS; Chatham Lodging as CLDT.

**Acceptance Scenarios**:

1. **Given** a listed company whose first SEC ticker has no prices, **When** another of its tickers
   is the same instrument with prices, **Then** that ticker prices the company.
2. **Given** a company with a common stock and preferred shares, **When** it is priced, **Then** the
   common stock is used.
3. **Given** a foreign company whose other ticker is a different instrument (an ADR against the
   ordinary share), **When** it is priced, **Then** that ticker is not used (no ADR ratios, out of
   scope) and the audit lists it.

---

### User Story 5 - Price coverage measured by one command (Priority: P2)

The researcher runs one command after any build and reads, per problem family, how many companies
are affected, the named cases' results, and coverage by year and status; the report quotes these
numbers, never typed in.

**Why this priority**: it turns the 11 November audit into a check that runs every time, so the next
unknown problem of this kind shows up as a number, and the report can state measured coverage
(constitution III).

**Independent Test**: on the code before the repair the command reproduces the 11 November counts;
after it, it shows the new counts.

**Acceptance Scenarios**:

1. **Given** a finished build, **When** the command runs, **Then** it prints each family's count
   with examples, the named cases' pass or fail, and coverage by year and status, in seconds.
2. **Given** a random sample of 30 remaining cuts, **When** each is checked by hand against the
   providers and the SEC filings, **Then** the share found wrong is recorded for the report.

---

### User Story 6 - Retrain, approve again, then the one holdout test (Priority: P1)

The three model notebooks run start to finish on the corrected data with their method unchanged; the
researcher reviews and approves each again; the holdout test then scores the newly frozen models and
the simpler levels frozen from the same data, once.

**Why this priority**: the reason for the repair (V2-65): the test of record should be of models
trained and tested on data without these gaps.

**Independent Test**: `sentinel holdout --check` passes on the new kept data; the frozen objects'
data fingerprints equal the kept copy's.

**Acceptance Scenarios**:

1. **Given** the corrected export, **When** each model notebook runs, **Then** it applies the same
   rules (folds, the one-standard-error rule, calibration, bands) and records its results.
2. **Given** the researcher's approval of the three models, **When** the holdout is prepared,
   **Then** a copy of the export they were built on is kept, the simpler levels are frozen from it
   and shown to reproduce the notebooks' records, and the check passes.
3. **Given** all of the above, **When** the researcher runs the holdout, **Then** it runs once,
   by Tuesday 17 November if everything before it is done, so the report of 18 November includes
   it; never on a partly repaired pipeline or on models not approved again: if they are not ready
   by Monday 16 November in the evening, it runs after the hand-in (before 26 November) and the
   report of 18 November says the test is still to come (researcher, 11 Nov).

---

### Edge Cases

- A company that changed tickers more than once (A → B → C): every switch is joined and checked.
- A merger in which the surviving legal company (same CIK) took the other company's ticker (ACE
  Ltd became Chubb Ltd and took CB): the surviving company keeps its own history under its old
  ticker (ACE); the earlier holder of CB keeps its own (Chubb Corp).
- A ticker change on the same day as a reverse split: the continuity check allows for the split.
- A company that traded over the counter before listing on an exchange under another ticker: the
  OTC history is joined when a provider has it.
- A company that was a blank-check company (SPAC) before its merger, under the SPAC's ticker:
  [NEEDS CLARIFICATION: does its history include the SPAC's pre-merger prices?].
- A typo in one insider filing naming another company's ticker for a day: it neither cuts nor
  joins anything (V2-63, extended).
- An old ticker whose prices no provider has: the gap stays and the audit records it.
- The Tiingo plan ends on 26 November: downloads after that are impossible; what is stored stays.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A company's price history MUST combine every ticker the company used, each for the
  period it was the company's, back to 1 January 2010, where a provider has prices for it.
- **FR-002**: Which company a ticker belonged to in a period MUST rest on evidence for that company
  and period: its own insider filings or SEC ticker lists, or a provider's record whose company name
  matches one of the company's SEC names; each join MUST pass a continuity check at the switch
  (the series meet within a few trading days, and the price levels agree once splits are allowed
  for). A join that fails is not made and is listed in the audit with its reason.
- **FR-003**: A history MUST NOT be cut at an exchange move or where a provider's coverage begins;
  a provider's listing record MUST cut a history only where it shows a different company held the
  ticker before.
- **FR-004**: Another company's use of a ticker that overlaps the company's own use in time MUST NOT
  cut the company's history (sister companies and typos; V2-63 extended to uses ending on the same
  day or overlapping in part). A company that is not the listed holder of a ticker another company
  holds at the same time MUST NOT take that ticker's prices.
- **FR-005**: The part of a series before a hole of more than one year MUST NOT be used for a
  company unless the company's own evidence covers that part.
- **FR-006**: A listed company MUST be priced from its first SEC ticker with a usable series of the
  same instrument, the common stock before preferred shares, units, warrants and notes; an ADR and
  its ordinary share MUST NOT stand in for each other (no ratios: out of scope).
- **FR-007**: A disappeared company MUST be priced across all its tickers (FR-001 to FR-005) up to
  its last trading day; prices ending over a year before its last report MUST be classified in the
  audit (renamed, moved to over-the-counter trading, unknown).
- **FR-008**: The disappeared US companies with insider filings and no prices MUST be measured by
  the audit, a random sample of 30 classified by hand (never traded, traded but not found), and
  recovered where a rule can find their prices.
- **FR-009**: Prices fetched for old tickers MUST be stored as raw files with manifest lines, and
  fetched from Tiingo only before 26 November 2026; raw files MUST never be edited or deleted.
- **FR-010**: The prices on day D and every feature built from them MUST NOT depend on records
  dated after D (the truncation test keeps passing); a company's 2012–2022 training rows MUST NOT
  change when it changes its ticker later (a test).
- **FR-011**: One command MUST report, after any build, the counts of each problem family of the
  11 November audit with examples, the named cases' results and coverage by year and status; on the
  code before this feature it reproduces the 11 November counts.
- **FR-012**: The named cases MUST pass: MGP Ingredients and Viavi priced from 2010 under their old
  tickers; Ingersoll Rand from Gardner Denver's first trading day (2017); Digital Realty from 2010,
  its operating partnership without DLR prices; Palatin and AMN Healthcare from 2010; Standard
  BioTools without LaBranche's prices and with its Fluidigm years; Heidmar without the 2010 block;
  Telephone & Data Systems priced; Chatham Lodging priced from its common stock; Xcerra and Hanger
  across their tickers; Fabrinet still from 2010.
- **FR-013**: After the repair the layers MUST be rebuilt and `sentinel verify` MUST find a full
  rebuild identical to the daily update; the EDA notebooks MUST be re-run and their findings
  updated where numbers move.
- **FR-014**: The three model notebooks MUST be re-run start to finish on the corrected export with
  their method unchanged and presented to the researcher; only models the researcher approves again
  are frozen.
- **FR-015**: The holdout test MUST then use a kept copy of the export the approved models were
  built on, the simpler levels frozen again from it and shown to reproduce the notebooks' records,
  and pass `sentinel holdout --check`; no answer whose window starts in 2023 or later is computed
  before the researcher's single run (constitution IV).
- **FR-016**: The decision (V2-65), each new rule, and the audit's counts before and after MUST be
  recorded in `docs/decisions.md`; the model report MUST state the data the models were trained on
  and the coverage the audit measured.

### Key Entities

- **Ticker use**: a company's use of a ticker over a period, with its evidence (its own insider
  filings, the SEC's lists, a provider's record) and whether another company used it at the same
  time.
- **Price series**: one provider's daily prices for one ticker, with its first and last day and the
  provider's company name.
- **Price history**: a company's joined history: segments, each from one series and ticker, with
  the reason for each switch and each cut.
- **Audit result**: per build, each problem family's count and examples, the named cases' results,
  coverage by year and status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: At least 95% of the 256 listed companies with a clearly wrong cut on 11 November have
  prices back to 2010 or to the first day their own evidence supports.
- **SC-002**: Of the 370 listed companies with an unjoined ticker change, every one whose old prices
  a provider has is joined or listed with the reason the join failed.
- **SC-003**: No listed company's history holds a hole of more than one year without a recorded
  reason.
- **SC-004**: Every named case of FR-012 passes.
- **SC-005**: Two consecutive daily updates with no rule change leave the 2012–2022 training rows
  identical.
- **SC-006**: In a random sample of 30 cuts that remain, at most 3 are found wrong by hand, and the
  measured share is in the report.
- **SC-007**: A full rebuild equals the daily update; the truncation test passes; the holdout
  answers are computed only by the researcher's single run.
- **SC-008**: The researcher approves the three retrained models before the holdout test.

## Assumptions

- This changes how prices are matched to companies (the method), not any answer's definition;
  `config/risk_params.yaml` stays untouched. It is a deliberate exception to the frozen cleaning
  (V2-33), as V2-63 was, agreed by the researcher (V2-65).
- One CIK is one legal company: a history under the same CIK across a rename or merger is the
  company's own (Chubb Ltd's years as ACE Ltd).
- ADR ratios stay out of scope: a foreign company priced through an ADR keeps its current pricing.
- The models of 9 November and their kept export stay on record; the retrained, re-approved models
  replace them as the holdout's frozen objects. The extra dilution record of 10 November is then
  superseded.
- The model method (folds, levels, the one-standard-error rule, calibration, bands) is unchanged;
  the levels chosen may change with the data, by the same rules.
- Tiingo downloads are possible until 26 November 2026; the daily update runs the checked-out
  branch at 10:00, so the branch stays working at that hour.
- Product v1 is due on 17 November and the report on 18 November.
