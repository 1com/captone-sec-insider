# Feature Specification: Project Skeleton, SEC Insider-Data Ingest and Provisional Delisted-Candidate List

**Feature Branch**: `001-skeleton-sec-ingest` (not yet created; the repository is on `main`)

**Created**: 2026-10-22

**Status**: Draft

**Input**: User description: "Feature 001 — Project skeleton, SEC insider-data ingest, and provisional delisted-candidate list (docs/initialplan.md Step 0, Step 1, and a provisional early version of Step 5). docs/initialplan.md v2.1 is the source of truth; the constitution in .specify/memory/constitution.md applies. Scope: (1) runnable skeleton with one command per pipeline step, a parameter file holding every Appendix E parameter, secrets read from an untracked file, tests and linting wired up; (2) download all 83 quarterly SEC Insider Transactions data sets, 2006 Q1 – 2026 Q3, from both SEC folder layouts, under SEC fair-access rules, stored immutably with a hashed manifest, idempotent and resumable; (3) a provisional delisted-candidate list built with the pilot's simplified gates, signal dates from 2016, likely-delisted issuers ranked clusters first, labelled provisional and never used for returns. Out of scope: any price fetching (pending a decision on Tiingo's Starter-plan no-storage clause, ToS §1.6(a)); typed staging tables, entities, production gates and events. Success: help output works; 83 files with hashes; candidate counts in the range of the pilot in §5.2; done in time to start a price pull before 31 October 2026."

## Context

This feature covers the start of the plan's critical path (Step 0 → Step 6 → Step 7, `docs/initialplan.md` §9.3). Delisted-stock prices gate everything downstream. On 2026-10-22 the researcher decided to buy one month of Tiingo Power, because the free plan forbids storing Tiingo data (ToS §1.6(a)). That removes the 500-symbol budget, so the list covers every year from 2006, and the start of the labelled window can be revisited before the pre-registration tag. The list of delisted companies to price was produced by the pilot but never saved, so it must be rebuilt from the SEC data before any price pull can start. This feature delivers that list and the foundation it rests on. It does not fetch any prices.

## User Scenarios & Testing *(mandatory)*

The actors are **the researcher** (the project owner, who runs the pipeline) and **the reviewer** (the course supervisor, who must be able to verify the inputs and the pre-registered parameters).

### User Story 1 - Fetch the complete SEC insider archive (Priority: P1)

The researcher runs one command and ends up with all 83 quarterly Insider Transactions data sets (2006 Q1 – 2026 Q3) on disk. Each file is unchanged from what the SEC served and recorded in a manifest. If the run is interrupted, running it again picks up where it stopped. The SEC's fair-access rules are respected throughout.

**Why this priority**: every later step reads these files. Without them there is no candidate list, no events and no study.

**Independent Test**: run the download on an empty data directory, then run the verify command. It should report 83 files and 83 matching hashes. Interrupt a second fresh run partway through, rerun it, and confirm that only the missing files are fetched.

**Acceptance Scenarios**:

1. **Given** an empty raw-data directory and a configured SEC contact, **When** the researcher runs the download, **Then** 83 quarterly files are stored and the manifest holds one entry per file with source URL, quarter, fetch time, size and SHA-256 hash.
2. **Given** a completed download, **When** the researcher runs it again, **Then** no file is fetched again and the command reports that all 83 are present and verified.
3. **Given** a download interrupted after some files, **When** the researcher reruns it, **Then** only the missing quarters are fetched, and no partial file is ever left under a final file name.
4. **Given** no SEC contact configured, **When** the researcher runs the download, **Then** the command refuses to contact the SEC and explains what to configure.
5. **Given** a stored file whose contents no longer match its manifest hash, **When** the researcher runs verify, **Then** the mismatch is reported by quarter and the file is not silently replaced.

---

### User Story 2 - Produce the provisional delisted-candidate list (Priority: P2)

From the downloaded archive alone, the researcher produces a ranked list of companies that (a) had at least one cluster (A) or solo CEO/CFO (B1) purchase event with a signal date from 2006 onward, and (b) no longer appear in the SEC's current list of active tickers. Clusters come first. Each row records the last ticker the company reported, so the later price pull knows what to ask for. A summary shows how the counts compare with the pilot.

**Why this priority**: this list is the input to the delisted-price pull, which is on the critical path for every later step.

**Independent Test**: with the archive present, run the candidate-list command. Check that the summary's counts for each start year are in the same range as §5.2 of the plan, that the per-year counts track Appendix A.3, and that the funnel counts for 2019 Q1 and 2023 Q1 track Appendix A.1.

**Acceptance Scenarios**:

1. **Given** the full archive, **When** the researcher builds the list, **Then** each candidate row shows: SEC company identifier (CIK), company name, last reported ticker, all distinct reported tickers, number of A and B1 events (in total and from the labelled-window start), first and last signal dates, a likely-delisted flag, and a flag for whether the ticker appears in Tiingo's public list of supported tickers.
2. **Given** the list is built, **When** the researcher opens it, **Then** issuers with at least one cluster event come before B1-only issuers, each tier is ordered by most recent signal date (newest first), and ties are broken by CIK.
3. **Given** the list is built, **When** the researcher reads the run summary, **Then** it shows, for each start year in plan §5.2 (2006, 2009, 2011, 2014, 2016): A + B1 events, companies, delisted companies found in Tiingo's list, and delisted companies not found there. It also shows A and B1 counts per year from 2006 onward and the gate funnel for 2019 Q1 and 2023 Q1.
4. **Given** the same archive and parameters, **When** the list is built twice, **Then** the two outputs are identical.
5. **Given** any output of this step, **When** anyone inspects it, **Then** it is visibly marked provisional, in its name and in its contents, and it sits apart from the warehouse's production layers.

---

### User Story 3 - One parameter file and a runnable project foundation (Priority: P3)

The researcher and the reviewer can see every pre-registered number in one place, checked automatically against the plan's parameter register. The project has a single command-line entry point that lists every pipeline step, a test suite and a lint check that run offline, and secrets that cannot leak into the repository.

**Why this priority**: Principle III requires every numeric parameter to live in the parameter file before the pre-registration tag. Doing it now means no threshold in Stories 1 and 2 is hard-coded. In practice, the command entry point and secrets handling are built first because Stories 1 and 2 depend on them, but on their own they deliver no research value.

**Independent Test**: on a fresh clone, run the setup command and then the help command. Every pipeline step from Step 0 to Step 21 is listed. The test suite and lint check pass without network access, and the parameter check passes.

**Acceptance Scenarios**:

1. **Given** a fresh clone, **When** the researcher runs the help command, **Then** every pipeline step of plan §9.2 is listed with a one-line description, grouped by phase.
2. **Given** a step not yet built, **When** the researcher invokes it, **Then** the command exits with a failure status and a message saying the step is not yet implemented, rather than appearing to succeed.
3. **Given** the parameter file, **When** the automated parameter check runs, **Then** it confirms that every row of the plan's Appendix E has a matching entry with the register's value and sensitivity variants.
4. **Given** a secrets file containing the SEC contact and the Tiingo key, **When** any command runs or logs, **Then** the Tiingo key never appears in output, logs, the manifest or any tracked file.

---

### Edge Cases

- **SEC rejects the request (HTTP 403, usually a missing or malformed User-Agent).** Stop at once with a clear message. Do not retry, because retrying a rejected client is what triggers SEC blocking.
- **SEC throttles (HTTP 429) or has a server error (5xx), or the network times out.** Retry with increasing waits up to a configured limit, then mark that quarter failed and continue with the others.
- **A quarter is in neither SEC folder layout** (for example, a quarter not yet published). Report it as missing, continue with the rest, and exit with a failure status listing the missing quarters.
- **A downloaded file is not a readable archive, or lacks a required table.** Treat it as a failed download: do not keep it under its final name.
- **The disk fills up or the process is killed mid-file.** No partial file appears under a final name, and the manifest never lists an incomplete file.
- **A file exists in the raw directory but is not in the manifest** (for example, copied in by hand). Report it as unrecorded and leave it alone. Do not adopt it into the manifest automatically.
- **The SEC republishes a corrected quarter.** The stored copy stays as first fetched. Fetching a replacement happens only on explicit request and is kept as a separate, dated copy, so earlier results stay reproducible.
- **Columns change between years** (for example, the 10b5-1 checkbox exists only from 2023, and column order or text encoding varies). Where the checkbox field is absent, the list treats it as not ticked and relies on footnote screening, as the pilot did.
- **The same filing appears in two quarterly files.** Count it once, keyed by accession number.
- **A blank, reused or changed ticker.** Blank tickers are recorded as blank and counted once, as in the pilot. The last reported ticker is taken from the issuer's most recent filing, and all distinct tickers are kept.
- **Look-ahead in the likely-delisted flag.** The flag uses today's SEC ticker map, so it is not point-in-time. That is acceptable only because the list prioritises a price pull. It must never feed events, features or labels.
- **Events in the holdout period (2023 – 2026).** The list counts holdout-period events but uses no prices and no outcomes, so the holdout stays sealed (Principle III). The pilot did the same.

## Requirements *(mandatory)*

### Functional Requirements

**Project foundation**

- **FR-001**: The project MUST provide a single command-line entry point whose help output lists every pipeline step in plan §9.2 (Steps 0–21, plus the parallel product track), grouped by phase, with a one-line description of each.
- **FR-002**: Invoking a step that is not yet built MUST end with a failure status and a "not yet implemented" message.
- **FR-003**: The project MUST hold every parameter from the plan's Appendix E in one parameter file (`config/params.yaml`, as named by the constitution), with its value and its sensitivity variants. Every threshold this feature uses MUST be read from that file, never written directly into code.
- **FR-004**: An automated check MUST fail if any Appendix E row has no matching entry in the parameter file, or if a value differs from the register.
- **FR-005**: The SEC contact and the Tiingo key MUST be read from the local, git-ignored secrets file. Commands that contact the SEC MUST refuse to run if no contact is configured.
- **FR-006**: Secrets MUST NOT appear in console output, logs, the manifest, or any tracked file.
- **FR-007**: The automated test suite and the lint check MUST run without network access and pass on a fresh clone.

**SEC archive**

- **FR-008**: The system MUST download every quarterly SEC Insider Transactions data set in the range set by the parameter file (2006 Q1 – 2026 Q3, 83 files), finding each file in whichever SEC folder layout holds it.
- **FR-009**: All SEC requests from a run MUST, taken together, stay at or below 10 requests per second, and every request MUST carry a User-Agent containing the configured contact.
- **FR-010**: Throttling, server errors and timeouts MUST be retried with increasing waits up to a configured limit. A request the SEC rejects (HTTP 403) MUST NOT be retried. A failed quarter MUST NOT stop the other quarters, and the run MUST end with a failure status listing every failed quarter.
- **FR-011**: Each file MUST be written so that it appears under its final name only when it is complete. Once stored, it MUST never be modified or overwritten.
- **FR-012**: The manifest MUST hold one entry per stored file: source URL, quarter, fetch time (UTC), size in bytes and SHA-256 hash. An entry is added only after its file is complete and verified.
- **FR-013**: Before a file is accepted, the system MUST confirm that it is a readable archive containing at least the submission, reporting-owner, non-derivative transaction and footnote tables.
- **FR-014**: Rerunning the download MUST skip every quarter already stored with a hash that matches the manifest, and fetch only missing quarters.
- **FR-015**: A verify command MUST re-hash every stored file against the manifest without network access, and report missing, mismatched and unrecorded files.

**Provisional delisted-candidate list**

- **FR-016**: The list MUST be built from the stored archive alone, with no price data, using the pilot's simplified gates from Appendix A:
  - original Form 4s only;
  - non-derivative purchases (code P, shares acquired) of common stock;
  - purchases excluded if the 10b5-1 checkbox is ticked (where the field exists) or if a footnote referenced by the transaction mentions a pre-planned purchase plan or an offering;
  - at least $10,000 per reporting owner per filing, filed within 30 days of the trade;
  - a transaction price of at least $2, standing in for the market-price floor.
- **FR-017**: Events MUST follow the pilot's definitions, detected across quarter boundaries:
  - **cluster (A):** clean purchases filed in the 14 calendar days ending on the signal date, from at least two distinct buyers, totalling at least $100,000;
  - **solo CEO/CFO (B1):** a CEO or CFO buying at least $100,000 in that window, with no other buyer;
  - a 91-calendar-day cooldown per issuer and group.
  All reporting owners on one joint filing count as a single buyer.
- **FR-018**: Events MUST be detected over the full insider data period (2006 onward), and every company with an event in any year is a potential candidate. Each event MUST be flagged for whether it falls on or after the labelled-window start in the parameter file (1 January 2016), so the list still serves the current design while the start year stays open until the pre-registration tag.
- **FR-019**: A company MUST be flagged likely delisted when its CIK does not appear in the SEC's current company-ticker map. The match is by CIK, not ticker, because tickers are reused by other companies.
- **FR-020**: For each likely-delisted company, the list MUST record whether its last reported ticker appears in Tiingo's public list of supported tickers. That list MUST be processed in memory only, and only the per-company match flag is saved, consistent with Tiingo's Starter-plan terms (ToS §1.6(a)).
- **FR-021**: The list MUST contain the fields and ordering in User Story 2, scenarios 1–2. Ordering MUST be deterministic, so the same inputs produce an identical output.
- **FR-022**: The run MUST produce a summary that can be compared directly with the plan: the §5.2 table (one row per start year), A and B1 counts per year (Appendix A.3), and the gate funnel for 2019 Q1 and 2023 Q1 (Appendix A.1).
- **FR-023**: Every output of the list MUST be labelled provisional, in its name and contents, and stored apart from the warehouse's production layers.

### Key Entities

- **Quarterly data set**: one SEC archive for one calendar quarter, containing the Form 3/4/5 tables (submissions, reporting owners, transactions, holdings, footnotes). Identified by its quarter.
- **Manifest entry**: the record of one stored file — quarter, source URL, fetch time, size and hash. The manifest is the proof that the raw inputs are unchanged.
- **Parameter**: one row of the plan's parameter register — name, value, units, basis and sensitivity variants.
- **Provisional event**: a cluster (A) or solo CEO/CFO (B1) event found with the pilot's simplified gates — issuer, group, signal date, buyers and total value. Used only to build the candidate list.
- **Delisted candidate**: one company with at least one provisional event from 2006 that is no longer in the SEC's active-ticker map. Holds its tickers, event counts, dates, Tiingo-list flag and rank.
- **Funnel count**: rows entering and leaving each simplified gate in one quarter, used to compare with the pilot.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a fresh clone, the researcher reaches the full list of pipeline steps with one setup command and one help command.
- **SC-002**: After the download, the verify command reports all 83 quarters present with 0 hash mismatches.
- **SC-003**: Rerunning the download after it has completed fetches 0 files and finishes in under one minute.
- **SC-004**: The full download finishes in under one hour on a home broadband connection, and the request log never shows more than 10 SEC requests in any one-second span.
- **SC-005**: The raw count of purchase lines (code P, shares acquired) for 2019 Q1 and 2023 Q1 is within 1% of Appendix A.1 (12,796 and 6,539). Any larger gap is explained in the run notes.
- **SC-006**: Every row of the §5.2 table is within ±15% of the pilot on each of: A + B1 events, companies, delisted companies in Tiingo's list and delisted companies not matched. For example, the 2016 row is 11,162 / 4,039 / 955 / 340 and the 2006 row is 21,904 / 6,682 / 1,982 / 1,233. Any larger gap is explained before the list is used.
- **SC-007**: Building the list twice on the same inputs gives identical outputs.
- **SC-008**: The candidate list is ready by 27 October 2026, so the price pull can start at the beginning of Week 2 (plan §9.3).
- **SC-009**: The test suite and lint check pass offline, and a scan of the repository and its history finds no secrets.

## Assumptions

- **The 2026 Q3 data set is published.** This was confirmed on 21 October 2026, so 83 quarters are available.
- **The pilot's code was not kept.** The simplified gates are rebuilt from the descriptions in Appendix A, so counts will not match exactly; SC-005 and SC-006 set the tolerances.
- **Joint filings count as one buyer.** This is a cheap stand-in for the production rule that merges co-filers into one entity (§6.3). It errs toward fewer clusters than counting every owner separately, and toward more than the production rule, which also merges owners across filings.
- **CEO and CFO are identified from the officer-title text**, using common spelling variants, as in the pilot.
- **The likely-delisted flag uses today's ticker map.** This is look-ahead and acceptable only for prioritising the price pull (see Edge Cases).
- **Tiingo's supported-ticker list is a public file** that needs no API key and uses none of the monthly symbol allowance.
- **The researcher runs everything on their own machine**, with enough free disk space for the raw archive (expected to be a few gigabytes).
- **Out of scope** (later features):
  - fetching prices from Tiingo or Yahoo (a later feature, using the one-month Tiingo Power plan decided on 2026-10-22);
  - typed staging tables, point-in-time entities, the production gates G1–G8, production event detection and the symbol map (plan Steps 2–6).
