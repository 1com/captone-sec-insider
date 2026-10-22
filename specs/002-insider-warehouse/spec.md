# Feature Specification: Insider Warehouse — Staging, Point-in-Time Entities, Production Gates, Preliminary Events and Symbol Map

**Feature Branch**: `002-insider-warehouse`

**Created**: 2026-10-22

**Status**: Draft

**Input**: User description: "Feature 002 — Insider warehouse: staging, point-in-time entities, production gates, preliminary events and the symbol map (docs/initialplan.md v2.2 Steps 2–6; §6.1–6.4; constitution v2.0.1 applies). Builds on feature 001. Course-project level: choose what compiles easily, not institutional-grade completeness. Scope: (1) load all 83 quarterly archives into typed staging tables in the single warehouse, handling column drift, with row counts matching the source files; (2) point-in-time insider entities and roles; (3) production gates G1–G6, all transaction types kept, clean purchases with holdings before and after, a per-quarter funnel; (4) preliminary events A, B1, B2 used to choose which companies to price; (5) a symbol map with intended price source and match quality, Tiingo final-ticker convention supported in memory until the paid month, and EDGAR headers of every signal filing for SIC at filing and acceptance time. Quality gates: unit tests, truncation test, data-quality tests, hand audits of 50 entities and 50 excluded plus 50 kept gate rows. Out of scope: prices, delistings, XBRL, costs, final detection, labels, features, product. Success: counts match, funnel reconciles, event counts compared with feature 001, truncation test passes, audits recorded, symbol-map coverage reported, headers fetched, full rebuild under 30 minutes, done by 28 October 2026."

## Context

Feature 001 downloaded the raw SEC archives and built a *provisional* list of delisted companies using the pilot's simplified rules and today's ticker map, which is look-ahead. This feature builds the **production** insider data that the research runs on. It follows the plan's full rules (§6.1–6.4) and uses only information that was public at the time. It ends with the list of companies and tickers that the price pull (feature 003) needs.

The actor throughout is **the researcher**. **The reviewer** (course supervisor) relies on the audits and tests to trust the result.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A typed, verified copy of every insider filing (Priority: P1)

The researcher runs one command and gets every table of all 83 quarterly archives loaded into the project's analysis database. Dates are stored as dates and amounts as numbers, and column changes over the years are handled. The row count of every table in every quarter matches the source file exactly. Rerunning the command on the same raw files gives the same result.

**Why this priority**: every later step (entities, gates, events, the product's insider lookup) reads these tables. If the load is wrong, everything downstream is wrong.

**Independent Test**: build the staging layer from the stored archives and compare row counts per table and quarter with the source files. Check that the schema-drift report shows the 10b5-1 checkbox column first appearing in 2023.

**Acceptance Scenarios**:

1. **Given** the 83 stored archives, **When** the researcher builds staging, **Then** every table of every quarter is present and its row count equals the number of data rows in its source file.
2. **Given** a quarter whose files lack a column that later quarters have, **When** it is loaded, **Then** the column exists with empty values and the load does not fail.
3. **Given** a value that cannot be read as its intended type (for example, a malformed date or a non-numeric share count), **When** it is loaded, **Then** the original text is kept alongside an empty typed value, and the count of such values is reported per column.
4. **Given** an unchanged set of archives, **When** staging is rebuilt, **Then** the result is identical.

---

### User Story 2 - Clean purchases by real economic insiders, with an audited funnel (Priority: P2)

The researcher gets the list of genuine, discretionary insider purchases. Owners who file together are treated as one economic insider, each with the role they held at the time. A funnel shows how many rows each rule removed in each quarter. Audit sheets let the researcher check samples by hand against the original filings.

**Why this priority**: these are the inputs to every event and every feature. The plan's two main correctness risks live here: counting a fund and its manager as two insiders, and keeping pre-planned or offering-related purchases.

**Independent Test**: on synthetic filings covering each rule and each merging edge case, confirm the expected kept and excluded rows, entity groupings and roles. Then run on the real data and confirm the funnel reconciles in every quarter.

**Acceptance Scenarios**:

1. **Given** a fund, its general partner and its manager reporting together on one filing, **When** entities are built, **Then** they form one entity from that filing's date onward.
2. **Given** two owners who first file together in 2019, **When** an event dated 2018 is examined, **Then** they are still separate entities at that date.
3. **Given** a director who becomes CEO in 2020, **When** events in 2019 and 2021 are examined, **Then** the person's entity has the director role in 2019 and the CEO/CFO role in 2021.
4. **Given** purchases failing each gate (an amendment, a non-P code, a disposal, preferred stock, a ticked 10b5-1 checkbox, a cited 10b5-1 footnote, a cited offering footnote, a filing below $10,000, a trade more than 30 days before filing), **When** the gates run, **Then** each is excluded by the right gate and recorded in the funnel.
5. **Given** a plan footnote cited only by a different line of the same filing, **When** the gates run, **Then** the line that does not cite it is kept.
6. **Given** a clean purchase, **When** it is recorded, **Then** it carries the entity, its role at the time, value, shares, and shares held before and after the purchase, summed over the entity's direct and indirect holdings reported in the filing.
7. **Given** the audit command, **When** the researcher runs it, **Then** it produces sheets of 50 random entities, 50 excluded rows and 50 kept rows. Each row links to the original EDGAR filing and has columns for the researcher's verdict and notes.

---

### User Story 3 - Preliminary events, compared with the provisional list (Priority: P3)

The researcher gets the preliminary cluster (A), solo CEO/CFO (B1) and solo other-insider (B2) events under the production rules. A comparison shows how they differ from feature 001's provisional events and why.

**Why this priority**: these events decide which companies need prices. The comparison confirms the production rules behave as expected: entity merging and the officer/director condition should reduce clusters.

**Independent Test**: on synthetic clean purchases, confirm the windows, entity counts, officer/director condition, solo rules and thresholds. Then run on the real data and read the comparison report.

**Acceptance Scenarios**:

1. **Given** clean purchases by two entities, one of them a director, filed 13 days apart and totalling $100,000 or more, **When** events are detected, **Then** one A event is recorded on the later filing date.
2. **Given** the same purchases by two entities that are both 10%-only owners, **When** events are detected, **Then** no A event is recorded.
3. **Given** a CEO entity buying $100,000 or more with no other entity buying in the window, **When** events are detected, **Then** a B1 event is recorded. A director in the same position produces B2, and a 10%-only owner produces nothing.
4. **Given** the full data, **When** the comparison report is produced, **Then** it shows counts per year and group next to feature 001's provisional counts, with the main reasons for the differences quantified.

---

### User Story 4 - A symbol map and filing headers ready for the price pull (Priority: P4)

The researcher gets, for every company with a preliminary event, the ticker or tickers it traded under over time, which price source should supply it, and how confident the match is. For every signal filing, they also get the company's industry code as of that filing and the time the filing became public.

**Why this priority**: the price pull cannot start without the right ticker for each date. Gate G7 and the industry features need the industry code at the time, and the T+1 entry rule needs the acceptance time.

**Independent Test**: confirm that every event company has a symbol-map entry or appears on the unmatched list. Confirm that headers exist for every signal filing or appear on the failure list. Spot-check known cases (for example, a company whose history Tiingo files under a bankruptcy `Q` ticker).

**Acceptance Scenarios**:

1. **Given** a company still listed today, **When** the symbol map is built, **Then** it maps to its current ticker with Yahoo as the intended source.
2. **Given** a delisted company, **When** the symbol map is built, **Then** it maps to the tickers reported in its Form 4 filings over their date ranges, with Tiingo as the intended source.
3. **Given** that the paid Tiingo month has not started, **When** Tiingo's final-ticker convention is applied, **Then** the resolution happens in memory and nothing from Tiingo is written to disk.
4. **Given** the signal filings of all preliminary events, **When** headers are fetched, **Then** each header is stored as a raw file with a manifest line, the industry code and acceptance time are recorded, and requests never exceed 10 per second.
5. **Given** a header that cannot be fetched or parsed, **When** the run ends, **Then** it is listed as a failure, and rerunning fetches only the missing headers.

---

### Edge Cases

- **A filing in two quarterly archives:** kept once, from the earlier quarter, by accession number (as in feature 001).
- **Several filings on one day by the same entity:** each is gated separately, then counted once per entity in event windows.
- **An owner on filings at different issuers:** entities are built per issuer. A person merged with a fund at one company is not merged with it elsewhere.
- **A merge that happens later:** two owners co-file in 2021, so they become one entity from 2021. Events from 2019 must still see two entities, which is what the truncation test checks.
- **Joint filings:** all owners on one filing are, by construction, one entity on and after that filing's date. "Per entity per filing" in G6 is therefore the filing's total.
- **Free-text titles:** titles such as "See Remarks", or a blank title on an officer, leave the role as "other officer". Only recognised CEO/CFO wording gives the CEO/CFO role.
- **Missing or zero price, or shares reported as a footnote reference only:** the line cannot be valued, is excluded by G6, and is counted in the funnel.
- **Holdings reported only in the separate holdings table, or missing:** shares held before and after use what the filing reports. A clean purchase with no reported holdings keeps empty values, and the count is reported.
- **A company with no ticker in any filing and none in today's SEC map:** listed as unmatched, not dropped silently.
- **A reused ticker** (the same ticker for two companies at different times): each mapping has a date range, and the company is identified by CIK, never by ticker.
- **Holdout-period data (2023 – 2026):** staging, entities, gates and preliminary events cover all years. No prices or outcomes are involved, so the holdout stays sealed.
- **SEC throttling or downtime during the header fetch:** the same retry, back-off and stop-on-403 rules as feature 001 apply, and the fetch can be resumed.

## Requirements *(mandatory)*

### Functional Requirements

**Staging**

- **FR-001**: The system MUST load every table of all 83 stored quarterly archives into one analysis database, in a staging area with one table per SEC table type, reading only from the stored raw files.
- **FR-002**: Dates MUST be stored as dates, amounts and share counts as numbers, and flags as true/false. A value that cannot be converted MUST keep its original text, and per-column conversion failures MUST be counted and reported.
- **FR-003**: Columns that exist only in some years MUST be present for all years, empty where the source lacks them. A schema-drift report MUST list, per table, the years in which each column appears.
- **FR-004**: For every table and quarter, the loaded row count MUST equal the source file's data-row count. Each row MUST record its source quarter. Filings that repeat across quarters are kept in staging and resolved in the core layer (FR-009).
- **FR-005**: Rebuilding staging from the same raw files MUST give identical results.

**Entities and roles**

- **FR-006**: For each issuer, owners who appear together on any filing for that issuer MUST be merged into one entity from that filing's date onward. An entity at date T is a connected component of the co-filing graph built only from that issuer's filings dated on or before T.
- **FR-007**: Each owner's role at date T MUST come from the relationship flags and officer title on its filings for that issuer dated on or before T. CEO and CFO variants are recognised by the keyword rules in the parameter file. An entity's role at T is its most senior member's role, ranked CEO/CFO > other officer > director > 10% owner > other.
- **FR-008**: Entity membership and roles MUST be stored with valid-from dates, so any date T can be queried without using later filings.

**Gates and clean purchases**

- **FR-009**: Every Form 4 transaction line, of any code, MUST be kept in a core transaction table, deduplicated by accession and line, with one flag per gate.
- **FR-010**: Gates G1–G6 MUST be applied as specified in plan §6.2:
  - G1: original Form 4 only;
  - G2: non-derivative code P acquisitions;
  - G3: common stock by security title;
  - G4: no ticked 10b5-1 checkbox on the filing, and no cited footnote matching the plan keywords;
  - G5: no cited footnote matching the offering keywords;
  - G6: at least the minimum value per entity per filing, and filed within the timeliness limit of the trade.
  All thresholds and keyword lists MUST come from the parameter file.
- **FR-011**: Footnote screens MUST consider only the footnotes cited by that transaction line.
- **FR-012**: Each clean purchase MUST be recorded per entity per filing, with: issuer, filing date, entity, entity role at that date, total value, total shares, and shares held before and after the purchase, summed over the entity's direct and indirect holdings reported in the filing.
- **FR-013**: A funnel MUST record, for every quarter and gate, rows in, rows out and rows removed. It MUST reconcile: rows in = rows out + rows removed, and each gate's rows in = the previous gate's rows out.

**Preliminary events**

- **FR-014**: Events MUST be detected per issuer over clean purchases, with signal date T equal to the filing date of the Form 4 that completes the conditions, and window [T − 13 days, T] (cluster window from the parameter file):
  - **A:** at least 2 entities, at least one an officer or director, total at least the minimum value;
  - **B1:** exactly one entity, with the CEO/CFO role, at least the minimum value;
  - **B2:** exactly one entity, with the other-officer or director role, at least the minimum value. Owners holding only a 10% stake never qualify for B1 or B2.
- **FR-015**: Preliminary events MUST be clearly marked as preliminary, used to choose which companies to price, and stored apart from the final event table built in feature 003.
- **FR-016**: A comparison report MUST put the production preliminary counts per year and group next to feature 001's provisional counts. It MUST quantify the main sources of difference: entity merging, the officer/director condition, and the timeliness and value rules applied per entity.

**Symbol map and headers**

- **FR-017**: Every issuer with at least one preliminary event MUST have one or more symbol-map entries (ticker, valid date range, intended price source, match quality) or appear on an unmatched list with a reason.
- **FR-018**: Listed companies (present in the latest SEC ticker snapshot) MUST map to their current ticker with Yahoo as the intended source. Delisted companies MUST map to the tickers in their Form 4 filings over the date ranges in which each was reported, with Tiingo as the intended source.
- **FR-019**: The symbol map MUST support Tiingo's final-ticker convention: delisted histories filed under the final, often `Q`-suffixed, ticker on any US venue. Until the paid Tiingo month starts, any use of Tiingo's ticker list MUST be in memory only, and the stored symbol map MUST contain only SEC-derived tickers and flags.
- **FR-020**: The system MUST fetch the EDGAR index header of the signal filing of every preliminary event dated on or after the labelled-window start (2012-01-01; earlier events never need an industry code), within SEC fair-access rules (at most 10 requests per second, contact User-Agent, retries, stop on 403). Headers are stored as immutable raw files with manifest lines. The fetch MUST be resumable.
- **FR-021**: From each header, the system MUST record the issuer's SIC code as of that filing and the acceptance date and time. Headers that cannot be fetched or parsed MUST be listed as failures.

**Quality gates**

- **FR-022**: Unit tests on synthetic fixtures MUST cover:
  - each gate;
  - entity merging (joint filers, several filings on one day, later merges, owners whose roles change);
  - role ranking;
  - each event group and its thresholds.
- **FR-023**: A truncation test MUST show that deleting every record dated after T leaves entities, roles, clean purchases and preliminary events at T unchanged. It runs on synthetic fixtures and on a sample of real issuers and dates.
- **FR-024**: Data-quality tests MUST check unique keys in every core table, funnel reconciliation, and staging row counts against the source files.
- **FR-025**: An audit command MUST generate review sheets: 50 random entities (members, roles and the filings that merged them), 50 random excluded gate rows and 50 random kept rows, each with an EDGAR link and blank verdict and notes columns. The researcher's completed reviews MUST be recorded with the feature, with the error rates found.
- **FR-026**: Every layer MUST be rebuildable from the stored raw files by commands, with no network access except the header fetch.

### Key Entities

- **Staged table**: a typed copy of one SEC table across all quarters, each row tagged with its source quarter.
- **Entity**: an economic insider at one issuer: one or more reporting owners linked by co-filing, with membership valid from the date of the linking filing.
- **Entity role**: the most senior role among an entity's members as of a date, from CEO/CFO down to other.
- **Transaction**: one Form 4 transaction line of any code, with its gate flags.
- **Clean purchase**: one entity's qualifying purchases on one filing: value, shares, role at the time, and shares held before and after.
- **Funnel row**: rows in, out and removed for one gate in one quarter.
- **Preliminary event**: a group A, B1 or B2 event at an issuer on a signal date, with its member purchases, entity count and total value.
- **Symbol-map entry**: an issuer's ticker over a date range, with intended price source and match quality.
- **Filing header**: for one signal filing, the issuer's SIC code at that filing and the acceptance date and time.
- **Audit sheet**: a random sample of entities or gate rows, with links and verdict columns, for hand review.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For all 8 tables × 83 quarters, the loaded row count equals the source file's data-row count, with zero exceptions.
- **SC-002**: The funnel reconciles in every quarter and gate, with zero discrepancies.
- **SC-003**: The truncation test passes on all synthetic cases and on a sample of at least 20 real issuer-date pairs.
- **SC-004**: All three hand audits are completed and recorded. Gate decisions agree with the researcher's reading in at least 90% of sampled rows, and entity groupings in at least 90% of sampled entities. Any error pattern found is either fixed or documented.
- **SC-005**: Production preliminary event counts are reported next to feature 001's provisional counts per year and group. With feature 001's $2 transaction-price stand-in applied for comparison, the total number of clusters (A) is no higher than the provisional total (16,513 across 2006–2026, out of 21,969 events), and every difference larger than 15% in a year is explained. The production set itself has no price filter, because price floors come with prices in feature 003, so it is larger and is reported alongside.
- **SC-006**: At least 95% of preliminary-event companies have a symbol-map entry. The rest are listed with reasons.
- **SC-007**: Headers are recorded for at least 99% of signal filings. The rest are listed as failures.
- **SC-008**: A full rebuild of every layer from the stored raw files, excluding the one-off header fetch, completes in under 30 minutes on the researcher's machine.
- **SC-009**: The feature is complete by 28 October 2026 (plan Week 1), so the price pull can start at the beginning of Week 2.

## Assumptions

- **Course-project level.** Where a rule has a cheap version and an exhaustive one, the cheap version is used and documented (owner's standing preference).
- **Per entity per filing.** Co-filers are one entity by construction, so "per entity per filing" equals "per filing".
- **Preliminary events and the cooldown.** Preliminary events apply a 91-calendar-day cooldown per issuer and group, the plan's approximation of 63 sessions, so their counts compare with feature 001. Exact session-based cooldowns, G7, G8 and the floors come with final detection in feature 003. The set of companies to price does not depend on the cooldown.
- **Keyword rules.** The keyword rules for plan and offering footnotes and for CEO/CFO titles start from feature 001's versions. They move to a non-provisional section of the parameter file, because they are research rules that the pre-registration tag will lock.
- **Holdings before.** "Shares held before" is computed as shares held after minus shares bought, for each holding line the entity reports in the filing, then summed. Holdings reported only in the separate holdings table are included when they are common stock.
- **Symbol-map scope.** The map is required only for companies with a preliminary event. Other issuers are mapped on a best-effort basis from the SEC snapshot, for the future product lookup.
- **Headers.** Headers are fetched only for signal filings of preliminary events dated 2012 onward (about 20,000 including B2), not for every filing. Each is about 3 KB.
- **Hand audits.** The researcher completes them, about 1–2 hours. The system prepares the sheets and records the results.
- **Out of scope** (feature 003 and later): prices, delisting classification, shares outstanding and XBRL items, trading costs, final events, labels, features, the product.
