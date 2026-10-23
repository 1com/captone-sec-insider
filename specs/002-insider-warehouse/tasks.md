---

description: "Task list for feature 002: insider warehouse (staging, point-in-time entities, production gates, preliminary events, symbol map)"
---

# Tasks: Insider Warehouse

**Input**: Design documents from `specs/002-insider-warehouse/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: included. They are required by FR-022 – FR-024 and by the constitution's quality gates. In each story, write the test tasks first and confirm that they fail.

**Organization**: by user story:
- **US1 (P1)**: staging;
- **US2 (P2)**: entities, gates, funnel, audits;
- **US3 (P3)**: preliminary events and the comparison;
- **US4 (P4)**: symbol map and headers.

The stories depend on one another's *data* (each reads the previous layer), but each is **tested independently** on synthetic fixtures run through the fixture pipeline in T009.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelisable (different files, no dependency on incomplete tasks)
- **[Story]**: US1–US4. Setup, Foundational and Polish tasks carry no story label.

---

## Phase 1: Setup

- [X] T001 Confirm branch `002-insider-warehouse` is checked out and the feature 001 baseline passes: `uv run pytest` (85 passed) and `uv run ruff check .`.
- [X] T002 [P] Create packages `src/sentinel/core/__init__.py` ("Production insider layers: staging, entities, gates, symbols.") and `src/sentinel/events/__init__.py` ("Event detection."), and the folder `tests/integration/`. In `pyproject.toml`, add the pytest marker `"slow: needs the real data/warehouse.duckdb; skipped when absent"`.

---

## Phase 2: Foundational (blocks every story)

- [X] T003 Update `config/params.yaml`, as specified in contracts/params-rules.md:
  - **`rules` section**, added between `ops` and `provisional`, with `gate_common_title_regex`, `gate_excluded_title_regex`, `gate_plan_footnote_regex`, `gate_offering_footnote_regex` and `role_ceo_cfo_title_regex`. Copy the values verbatim from the matching `provisional.*` keys.
  - **`prelim_cooldown_calendar_days: 91`** in `rules`.
  - **In `ops`**: `sec_header_target_requests_per_second: 8` and `sec_headers_url_pattern: "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}-index-headers.html"`.
  - **`version: 5`**.
- [X] T004 Update `src/sentinel/config.py`:
  - `SECTIONS = ("registered", "ops", "rules", "provisional")`.
  - `load_params` compiles every `*_regex` in `rules` as well as in `provisional`, and checks `ops.sec_header_target_requests_per_second <= ops.sec_max_requests_per_second`.
  - `check_register` also rejects a `register` block in `rules`.
  - `Paths` gains `warehouse = data/warehouse.duckdb`, `sec_headers = data/raw/sec/headers` and `audits = specs/002-insider-warehouse/audits`.
- [X] T005 [P] Extend `tests/unit/test_config.py` and `tests/unit/test_params_register.py` to cover contracts/params-rules.md rules 1–5:
  - the four sections, with no key appearing in two of them;
  - no `register` block in `rules`;
  - every `rules` regex compiles in Python *and* in DuckDB (`select regexp_matches('x', ?, 'i')`);
  - the header rate is at most the ceiling, which is at most 10;
  - `version == 5`.
- [X] T006 Implement `src/sentinel/warehouse.py`:
  - **`connect(paths, read_only=False)`**: creates the parent folder, and schemas `stg`, `core`, `evt` and `audit` if absent.
  - **`replace_table(con, name, select_sql, params=None)`**: `CREATE OR REPLACE TABLE … AS …` inside a transaction.
  - **`require_tables(con, names, run_first)`**: raises `MissingInput("run `sentinel <step>` first: missing <table>")`.
  - **`log_build(con, step, fingerprint, rows)`**: inserts into `core.build_log` (`step`, `started_at`, `finished_at`, `input_fingerprint`, `rows_written`).
  - **`table_exists`**.
- [X] T007 [P] Add a `Manifest` class to `src/sentinel/ingest/manifest.py`:
  - **Loading**: reads the existing entries once and builds indexes of paths and (`source`, `key`, `role=original`).
  - **`add(entry)`**: checks the same rules as `append`, then writes one line, flushes and fsyncs.
  - **Lookups**: `has_path(path)`, and `find_original(source, key)` in O(1).
  - **Compatibility**: the existing `append()` delegates to a temporary `Manifest`. Existing callers and tests stay unchanged.

  Add tests to `tests/unit/test_manifest.py`: 2,000 `add` calls complete in under 5 s with no duplicates accepted, and a reload sees every entry.
- [X] T008 [P] Create `src/sentinel/core/symbols.py`. Move `normalise`, `parse_supported`, `fetch_list`, `match` and `TiingoIndex` there from `src/sentinel/provisional/tiingo_list.py`, with their docstrings unchanged. Make `tiingo_list.py` re-export them (`from sentinel.core.symbols import ...`). Production code must not import `sentinel.provisional`; the reverse direction is allowed. Run `uv run pytest`, which must still pass unchanged, including `tests/unit/test_tiingo_match.py` and the guard test.
- [X] T009 Extend `tests/conftest.py` with:
  - **`archives(tmp_data, quarters: dict[str, dict[str, list[dict]]], checkbox_from="2023q1")`**: writes one synthetic zip per quarter with `build_quarter_zip` and records each as a manifest `original` (source `sec_insider_bulk`).
  - **Fixture `pipeline`**: given `archives`, runs the build steps in order (`stage`, `entities`, `gates`, `prelim`, `symbols`) on `tmp_data.warehouse`, stopping at a requested step, and returns the DuckDB connection.
  - **Row helpers**: `sub(...)`, `owner(...)`, `line(...)`, `holding(...)`, `note(...)`, matching those in `tests/unit/test_provisional_gates.py`.
  - **`slow` skip**: skip `slow` tests when `Paths.from_root(REPO).warehouse` does not exist.

**Checkpoint**: params version 5 loads, `uv run pytest` passes, and the fixture pipeline can be imported.

---

## Phase 3: User Story 1 — Typed, verified copy of every filing (P1) 🎯 MVP

**Goal**: all 8 tables × 83 quarters in `stg.*`, typed, with row counts equal to the files.

**Independent Test**: `test_stage.py` on synthetic archives, then `sentinel stage` on real data with 0 mismatches.

### Tests (write first)

- [X] T010 [P] [US1] Write `tests/unit/test_stage.py`, using `archives` with two quarters (`2019q1`, `2023q1`):
  - **Counts**: all 8 `stg` tables exist, and the per-(table, quarter) counts equal the rows written, as recorded in `stg.load_report`.
  - **Typing**: `filing_date` is DATE, `trans_shares` is DOUBLE, `equity_swap_involved` is BOOLEAN, and CIK `'0000036270'` becomes `'36270'`.
  - **Conversion issues**: a `TRANS_DATE` of `'31-FOO-2019'` and a `TRANS_SHARES` of `'F1'` become null, with rows in `stg.conversion_issue` holding the raw text.
  - **Drift**: `aff10b5one` is null for 2019 and typed for 2023.
  - **Key**: (`quarter`, `src_row`) is unique.
  - **Duplicates**: an accession present in both quarters appears twice in `stg.submission`.
  - **Determinism**: rebuilding gives identical sorted row hashes.

### Implementation

- [X] T011 [US1] Implement `src/sentinel/core/stage.py`:
  - **`TABLE_SPECS`**: for each of the 8 tables, the date columns (`*_DATE`, `PERIOD_OF_REPORT`, `DATE_OF_ORIG_SUB`), numeric columns (shares, price, value, conversion or exercise price, underlying shares), boolean columns (research R2) and CIK columns.
  - **`stage_all(con, archives)`**:
    1. Create each `stg.<table>` with typed columns plus `quarter` and `src_row`.
    2. For each archive and table, stream it with `sentinel.ingest.sec_tables.read_table` (all-text), adding `src_row` (1-based).
    3. Register it and `INSERT … SELECT` with `try_strptime(..., '%d-%b-%Y')::DATE`, `try_cast(... AS DOUBLE)`, the boolean mapping and `ltrim(cik, '0')`.
    4. Insert conversion failures (raw non-empty, typed null) into `stg.conversion_issue`.
    5. Write `stg.load_report` (`table_name`, `quarter`, `rows_expected` = file newline count − 1, `rows_loaded`, `columns`).
  - **`drift_report(con)`**: returns the quarters present for each column.
- [X] T012 [US1] Replace the `stage` stub in `src/sentinel/cli.py`. It loads archives from the manifest originals (`sentinel.provisional.load.stored_archives` is forbidden here, so add `stored_archives` to `sentinel.core.stage` or `ingest.manifest`). It prints the total rows, the conversion-issue counts per column (top 10), any `load_report` mismatches and the elapsed time; logs the build; and exits 1 on any mismatch.
- [X] T013 [US1] Run `time uv run sentinel stage` on the real data. Confirm 37,937,561 rows and 0 mismatches (SC-001), and record the counts per table, the conversion issues and the timing in `specs/002-insider-warehouse/run-notes.md`.

**Checkpoint**: the staging layer is complete and verified.

---

## Phase 4: User Story 2 — Clean purchases by real economic insiders, with an audited funnel (P2)

**Goal**: point-in-time entities and roles, every transaction with gate flags, clean purchases with holdings, a reconciled funnel and audit sheets.

**Independent Test**: synthetic edge cases pass, and the real funnel reconciles in every quarter.

### Tests (write first)

- [X] T014 [P] [US2] Write `tests/unit/test_entities.py`:
  - **Joint filing**: X and Y on one filing on 2019-03-01 give one `entity_id` from that date.
  - **Later merge**: X and Y file separately in 2018 and co-file on 2019-05-01, so they are two entities at 2019-04-30 and one at 2019-05-01.
  - **Same day**: two co-filings on one day (X+Y, Y+Z) are applied together, so X, Y and Z are one entity on that day.
  - **Per issuer**: the same owners at another issuer stay separate.
  - **W7 (monotonic)** and **W8** (every owner on an accession maps to one entity at its filing date).
  - **Roles**:
    - a director in 2019 and a CEO from 2021 gives director in 2020 and `ceo_cfo` in 2021;
    - a CEO who later files as director only gives `director` after that filing;
    - titles `"President & CEO"`, `"Chief Financial Officer"` and `"Principal Executive Officer"` give `ceo_cfo`;
    - an officer titled `"See Remarks"` gives `officer`;
    - an entity of director + 10% owner has seniority 2.
- [X] T015 [P] [US2] Write `tests/unit/test_core_gates.py`:
  - **Exclusions**: one excluded case per gate (G1–G6b), as in feature 001's gate tests, plus a missing price excluded by G6a.
  - **Cited footnotes only**: a plan footnote cited only by another line keeps this line.
  - **Checkbox**: a ticked box excludes every line of the filing.
  - **Timeliness**: 30 days kept, 31 days and negative lags excluded.
  - **Value**: just below `registered.g6_min_value` ($25,000 since D46) dropped, exactly at it kept, per filing.
  - **Entity and role**: a clean purchase's `entity_id` and `entity_role` are taken as of its filing date.
  - **Holdings**:
    - direct (after 1,000, bought 400) plus indirect (after 2,000, bought 0 on another line) gives before 2,600 and after 3,000;
    - two trades on one holding use the after-value of the last line;
    - an untraded common-stock `NONDERIV_HOLDING` row of 500 adds 500 to both;
    - a same-filing sale on the holding is added back to "before";
    - a negative "before" becomes null;
    - `opens_position` is true when "before" is 0.
  - **Deduplication**: by (`accession`, `line_sk`) across quarters.
  - **W5 and W6** hold.
- [X] T016 [P] [US2] Write `tests/unit/test_truncation.py`, with a synthetic two-year history of merges, a promotion and purchases at one issuer. For three cutoffs T, building with `cutoff=T` must give the same rows as the full build filtered to dates ≤ T, for `core.entity_member`, `core.owner_role` and `core.clean_purchase` (W9; events are added in T026).
- [X] T017 [P] [US2] Write `tests/unit/test_audit.py`:
  - **Layout**: the three sheets have exactly the columns in contracts/audit-sheets.md.
  - **Seed**: 2002 gives an identical sample on rerun.
  - **Stratification**: excluded rows are stratified by deciding gate when enough rows exist.
  - **Overwrite protection**: existing sheets are not overwritten without `force=True`.
  - **Summary**: correct counts and agreement = correct ÷ (correct + wrong), and blanks give exit 1.

### Implementation

- [X] T018 [US2] Implement `src/sentinel/core/entities.py`. Every function takes `cutoff: date | None` and `issuers: list[str] | None`.
  - **`build_filing(con)`**: creates `core.filing`, deduplicated as the first quarter per accession.
  - **`build_entity_members(con)`**: a Python union-find per issuer over owner CIKs, grouped by filing date (all of a day's filings unioned before emitting). Emits (`issuer_cik`, `owner_cik`, `entity_id` = `"{issuer}:{min owner}"`, `valid_from`) whenever an owner's component changes, and bulk-inserts via Arrow.
  - **`build_owner_roles(con, params)`**: SQL window functions over `stg.reportingowner` joined to `core.filing`. Gives the role and seniority per filing (research R4), with intervals collapsed when consecutive roles match.
- [X] T019 [US2] Replace the `entities` stub in `src/sentinel/cli.py`. It requires `stg.submission` and `stg.reportingowner`, prints counts (filings, owners, entities, multi-member entities, role intervals) and logs the build.
- [X] T020 [US2] Implement `src/sentinel/core/gates.py`, with `cutoff` and `issuers` arguments:
  - **`build_transactions(con, params)`** → `core.transaction`: the columns in data-model.md, `fn_ids` from every `*_fn` column, `value_usd`, and flags `g1_form4`, `g2_purchase`, `g3_common`, `g4a_no_checkbox`, `g4b_no_plan_fn`, `g5_no_offering_fn` and `g6a_timely_valued`, from `rules.*` and `registered.g6_timeliness`, plus `passes_lines`.
  - **`build_clean_purchases(con, params)`** → `core.clean_purchase`:
    - one row per filing whose passing lines total ≥ `registered.g6_min_value`;
    - `entity_id`, `entity_role` and `entity_seniority` by ASOF lookup at `filing_date`;
    - sorted `owner_ciks`;
    - holdings before and after as in research R5, using `stg.nonderiv_holding` common-stock rows of the same accession;
    - `opens_position`.
  - **`build_funnel(con)`** → `audit.funnel`: line gates plus G6b at filing level.
- [X] T021 [US2] Replace the `gates` stub in `src/sentinel/cli.py`. It prints rows per step, clean purchases and null-holdings counts; checks W5 and W6; exits 1 if the funnel does not reconcile; and logs the build.
- [X] T022 [US2] Implement `src/sentinel/core/audit.py`, as specified in contracts/audit-sheets.md:
  - **`make_sheets(con, out_dir, seed=2002, force=False)`**: three CSVs, EDGAR links, cited footnote text truncated to 500 characters, and excluded rows stratified by deciding gate.
  - **`summarize(out_dir)`**: returns the counts and rates per sheet.
- [X] T023 [US2] Add `audit sheets [--force]` and `audit summary` (a typer sub-app) to `src/sentinel/cli.py`. `summary` exits 1 if any verdict is blank.
- [X] T024 [US2] Run `uv run sentinel entities && uv run sentinel gates` on the real data. Record in `run-notes.md` the clean purchases, the funnel totals by gate, the null-holdings count and the timings (SC-002). Then run `uv run sentinel audit sheets`, and **hand off to the researcher** to fill in `verdict` and `notes` in the three sheets (about 1–2 hours). Implementation continues with US3 meanwhile.

**Checkpoint**: clean purchases exist, the funnel reconciles, and the audit sheets are with the researcher.

---

## Phase 5: User Story 3 — Preliminary events and the comparison (P3)

**Goal**: A/B1/B2 events with entities and roles as of T, and a comparison with feature 001.

**Independent Test**: synthetic event cases pass, and `comparison.md` explains every difference above 15%.

### Tests (write first)

- [ ] T025 [P] [US3] Write `tests/unit/test_prelim_events.py`:
  - **A**: a director and an outside entity 13 days apart, ≥ $100k → A on the later date. At 14 days apart → none.
  - **10%-only**: two 10%-only entities → no A.
  - **Promotion before T**: an owner promoted to director before T satisfies the officer/director rule.
  - **Merge before T**: two owners who merge before T count as **one** entity at T (no A).
  - **B1/B2**: CEO alone → B1; director alone → B2; other officer alone → B2; 10%-only alone → none; role `other` alone → none.
  - **Cooldown**: 90 days suppressed, 91 allowed, per group.
  - **Signal filing**: `signal_accession` is the highest accession on T.
  - **Flags**: `passes_price_standin` is false when any member line has price < $2; `in_labelled_window` is true from 2012-01-01.
- [ ] T026 [US3] Extend `tests/unit/test_truncation.py` so preliminary events at ≤ T are identical between the cutoff build and the full build (W9 complete).
- [ ] T027 [P] [US3] Write `tests/unit/test_compare.py`, using a small synthetic `events_PROVISIONAL.parquet` with feature 001's schema and a small `evt.prelim_event`:
  - the report has per-year counts for A, B1 and B2 under the 3 variants (research R8);
  - years differing by more than 15% are flagged;
  - the module does not import `sentinel.provisional`.

### Implementation

- [ ] T028 [US3] Implement `src/sentinel/events/prelim.py`: `detect_prelim(con, params, cutoff=None, issuers=None)` → `evt.prelim_event` and `evt.prelim_event_member`.
  - **Per issuer**: at each distinct clean-purchase date T, the window is [T − (`cluster_window` − 1), T]. Each purchase's owner maps to its entity at T, with the entity role at T, via SQL ASOF lookups on `core.entity_member` and `core.owner_role`.
  - **Groups**: as in data-model.md.
  - **Cooldown**: `rules.prelim_cooldown_calendar_days`.
  - **Other fields**: `passes_price_standin` (every member line has price ≥ `provisional.price_standin_floor`) and `in_labelled_window`.
- [ ] T029 [US3] Implement `src/sentinel/events/compare.py`: `compare(con, parquet_path, params)` → markdown, with a table per group and year for provisional, production, production + $2, and production + $2 without the officer/director rule, plus the % gaps and the flags. Explanations are written by hand after the run.
- [ ] T030 [US3] Replace the `detect-prelim` stub, and add `compare-provisional`, in `src/sentinel/cli.py`. The comparison writes `specs/002-insider-warehouse/comparison.md` and prints the totals.
- [ ] T031 [US3] Run `uv run sentinel detect-prelim && uv run sentinel compare-provisional` on the real data. Check SC-005: total A under production + $2 ≤ 16,513. Write the explanations for every flagged year into `comparison.md`, and the totals into `run-notes.md`.

**Checkpoint**: the preliminary events exist, and the differences from feature 001 are explained.

---

## Phase 6: User Story 4 — Symbol map and filing headers (P4)

**Goal**: every event company mapped or listed as unmatched; headers with SIC and acceptance time for signal filings from 2012.

**Independent Test**: `test_symbols.py` and `test_sec_headers.py` pass, and the real coverage is at least 95% (map) and 99% (headers).

### Tests (write first)

- [ ] T032 [P] [US4] Write `tests/unit/test_symbols.py`, with a synthetic SEC snapshot plus filings:
  - **Listed**: Nasdaq-listed → `yahoo`, `sec_current`, `valid_to` null.
  - **OTC**: OTC-only → `sec_current_otc`.
  - **Delisted**: tickers `ABC` (2014–2016) and `ABCD` (2017–2019) → two `tiingo` / `form4_history` rows with those date ranges.
  - **Reused ticker**: a ticker used by two CIKs stays separate.
  - **Unmatched**: no ticker → `symbol_unmatched` `no_ticker`; a name containing "Fund", "Trust" or "Income" with no exchange listing → `fund_like`.
  - **W10, W11**.
  - **Tiingo report**: with `fetch_list` monkeypatched, it returns counts and writes nothing under `tmp_path`.
- [ ] T033 [P] [US4] Write `tests/unit/test_sec_headers.py`, with fixture `tests/fixtures/edgar_header_form4.txt` (the Air Products header from research R9, public SEC data):
  - **Parsing**: `parse_header` gives SIC `2810`, its label, and `accepted_at_et` 2019-07-26 11:48:41. A header with no SIC in its `<ISSUER>` block gives SIC null.
  - **Selection**: only events with T ≥ 2012-01-01.
  - **Fetching** (respx):
    - stores `data/raw/sec/headers/2019/<acc>.txt` read-only, with one manifest line via `Manifest`;
    - a rerun skips stored headers (0 requests);
    - a 404 or parse error goes to `core.header_failure`;
    - a 403 raises `SecForbidden`;
    - the limiter target is 8.

### Implementation

- [ ] T034 [US4] Implement in `src/sentinel/core/symbols.py`:
  - **`build_symbol_map(con, snapshot_path, params, cutoff=None)`** → `core.symbol_map` and `core.symbol_unmatched`, as in research R7. Listed companies come from `sentinel.ingest.sec_reference.load_snapshot` (exchange OTC or None → `sec_current_otc`). Delisted ranges are the first and last filing date per normalised `symbol_raw` in `core.filing`. The scope is every issuer with a preliminary event, plus best-effort for all issuers in `core.filing`.
  - **`tiingo_coverage(con, params)`**: matches delisted event companies in memory and returns the counts of matched, `Q`-suffix and unmatched.
- [ ] T035 [US4] Implement `src/sentinel/ingest/sec_headers.py`:
  - **`signal_accessions(con, params)`**: events with `in_labelled_window`, or T ≥ the labelled start, that have no stored header.
  - **`fetch_headers(paths, params, client, limiter, policy, limit=None, retry_failures=False, on_progress=None)`**: `stream_to_file` to `.part`, rename, `chmod 0444`, `Manifest.add` with source `sec_filing_header` and key = accession.
  - **`parse_header(text)`**: SIC from the `<ISSUER>` block (`STANDARD INDUSTRIAL CLASSIFICATION:.*\[(\d{4})\]`), `ACCEPTANCE-DATETIME` (`%Y%m%d%H%M%S`, US Eastern), form type and filed-as-of date.
  - **`load_headers(con, paths)`**: re-parses every stored header into `core.filing_header`, with failures in `core.header_failure`.
- [ ] T036 [US4] Replace the `symbols` stub (with `--tiingo-report`) and add `fetch-headers` (`--limit`, `--retry-failures`) and `build` to `src/sentinel/cli.py`.
  - **`fetch-headers`**: uses a `RateLimiter(8, 10)`, holds `FetchLock`, prints progress every 500, and exits 5 on a 403.
  - **`build`**: runs stage → entities → gates → detect-prelim → symbols, then `load_headers` if any headers are stored, stopping at the first failure.
- [ ] T037 [US4] Run `uv run sentinel symbols --tiingo-report` on the real data and record coverage (SC-006: ≥ 95% mapped). Then `uv run sentinel fetch-headers --limit 20` as a smoke test, then the full fetch **in the background** (about 40 min). Then run `load_headers` and record the coverage (SC-007: ≥ 99%) and the failures.

**Checkpoint**: the price pull (feature 003) has its company and ticker list, and G7 has industry codes.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T038 [P] Add `check_invariants(con, params) -> list[str]` to `src/sentinel/warehouse.py`, covering W1–W8, W10 and W11 from contracts/warehouse-schema.md. `sentinel build` runs it at the end and exits 1 on problems. Add `tests/integration/test_warehouse_real.py` (`@slow`), which runs it on the real warehouse.
- [ ] T039 [P] Write `tests/integration/test_truncation_real.py` (`@slow`), as in research R10: 20 (issuer, T) pairs with seed 2002, from issuers with at least 5 clean purchases and at least one merge. Rebuild Steps 3–5 for each with `cutoff=T` and `issuers=[issuer]`, and compare with the full build at ≤ T. Run it, and record the result (SC-003).
- [ ] T040 Time a full rebuild: move `data/warehouse.duckdb` aside, run `time uv run sentinel build`, and confirm under 30 minutes (SC-008) and that `check_invariants` returns no problems. Record the results in `run-notes.md`.
- [ ] T041 Once the researcher has filled in the sheets, run `uv run sentinel audit summary` and confirm agreement ≥ 90% per sheet (SC-004). Record the rates and the error patterns in `run-notes.md`. Fix any systematic error found (for example, a missed footnote keyword) with a params version bump and a rebuild, and document it.
- [ ] T042 [P] Documentation:
  - **README**: the new commands, plus a "warehouse" section in the data layout.
  - **Plan decision log**: append **D44** to `docs/initialplan.md` §12: keyword rules and the preliminary cooldown move to the params `rules` section, locked by `prereg-v1`; preliminary events carry no price filter (floors come with prices); headers are fetched only for events from 2012.
  - **Plan data model**: update §8.2 with the new tables (`core.filing`, `core.owner_role`, `evt.prelim_event`, `core.filing_header`).
- [ ] T043 Run `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` (offline), then `uv run pytest -m slow` against the real warehouse. Walk through `quickstart.md` and record the outcomes in `run-notes.md`. Confirm `find data -iname '*tiingo*'` is empty.
- [ ] T044 With the researcher's approval, commit on `002-insider-warehouse` in small logical commits: params/config, warehouse and manifest, staging, entities and gates, events and comparison, symbols and headers, audits and docs.

---

## Dependencies & Execution Order

- **Setup (T001–T002)**, then **Foundational (T003–T009)**:
  - T003 → T004 → T005.
  - T006, T007 and T008 can run in parallel after T004.
  - T009 needs T006.
- **US1 (T010–T013)**: needs Foundational.
- **US2 (T014–T024)**: needs US1's tables for the real run (T024). Its tests use the fixture pipeline.
  - T018 → T019; T020 needs T018; T021 needs T020.
  - T022 and T023 need T020.
- **US3 (T025–T031)**: needs T018 and T020. T028 → T030 → T031; T029 → T030.
- **US4 (T032–T037)**: needs T028 (events define the scope). T034 and T035 can run in parallel; T036 needs both.
- **Polish (T038–T044)**: T041 waits for the researcher's verdicts from T024.

### Critical path (deadline 28 Oct)

T003 → T004 → T006 → T009 → T011 → **T013 (stage real data)** → T018 → T020 → **T024 (audit sheets to the researcher)** → T028 → T031 → T035 → **T037 (start the header fetch)** → T040 → T041

### The researcher's involvement

- **T024**: fill in three audit sheets of 50 rows each (about 1–2 hours). This can happen while US3 and US4 are built.
- **T041**: review the summary. Approve commits (T044).

---

## Parallel Examples

```bash
# Foundational, after T004
Task: "Manifest class (T007)"   Task: "move shared symbol helpers (T008)"   Task: "warehouse.py (T006)"

# US2 tests together
Task: "test_entities.py (T014)"  Task: "test_core_gates.py (T015)"  Task: "test_truncation.py (T016)"  Task: "test_audit.py (T017)"

# US4 tests together
Task: "test_symbols.py (T032)"   Task: "test_sec_headers.py (T033)"
```

---

## Implementation Strategy

1. **MVP**: Phases 1–3. Staging verified against the files (SC-001).
2. **US2**: hand the audit sheets to the researcher as early as possible (T024).
3. **US3, then US4**: start the header fetch in the background as soon as events exist (T037).
4. **Polish**: invariants, the real-data truncation test, rebuild timing, audit results, docs, commits.

### Notes

- **Provisional code**: `sentinel.provisional` stays untouched apart from the re-export in T008, and the guard test keeps it isolated.
- **Tiingo**: nothing from Tiingo is written to disk. `--tiingo-report` works in memory.
- **Keyword rules after the tag**: any change to the `rules` section after `prereg-v1` is a logged deviation (contracts/params-rules.md).
