---
description: "Task list for feature 001, daily data refresh"
---

# Tasks: Daily data refresh

**Input**: Design documents from `/specs/001-daily-data-refresh/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/raw-layout.md](contracts/raw-layout.md), [quickstart.md](quickstart.md)

**Tests**: included. The constitution's quality gates require them: a synthetic test for every table,
named real-data checks, the truncation test, and HTTP mocked (respx) so tests never touch the
network.

**Organization**: tasks are grouped by user story; each story is a stage that can be finished and
tested on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: the user story (US1–US5 of spec.md)
- Paths are from the repository root (single project: `src/sentinel/`, `tests/`)
- Heavy real-data runs use the memory cap: `systemd-run --user --scope -p MemoryMax=5G uv run …`

---

## Phase 1: Setup

**Purpose**: settings, paths and fixtures every story uses

- [X] T001 Add the schemas `stg_sec_form4_daily` and `ops` to `SCHEMAS` in src/sentinel/db.py
- [X] T002 [P] Add to `Paths` in src/sentinel/config.py: `sec_index` (`data/raw/sec/index`), `sec_form4` (`data/raw/sec/form4`), `sec_companyfacts` (`data/raw/sec/companyfacts`), `sec_submissions` (`data/raw/sec/submissions`), `logs` (`data/logs`), `update_lock` (`data/.update.lock`), `verify_db` (`data/verify.duckdb`), `serving_prev` (`data/serving.prev.duckdb`)
- [X] T003 [P] Add settings to config/sources.yaml and check them in `sources()` in src/sentinel/config.py: `sec.daily_index_url: "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{quarter}/master.{day}.idx"`, `sec.filing_text_url: "https://www.sec.gov/Archives/{file_name}"`, `sec.companyfacts_cik_url: "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"`, `sec.submissions_cik_url: "https://data.sec.gov/submissions/CIK{cik10}.json"`, `sec.document_requests_per_second: 8`, `sec.ownership_forms: ["3", "3/A", "4", "4/A", "5", "5/A"]`, `sec.detail_forms: ["8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A", "6-K"]`, `sec.periodic_forms: ["10-Q", "10-Q/A", "10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"]`, `prices.yahoo_window_days: 10`, `prices.yahoo_daily_batch_size: 200`, and a new section `update` (`min_free_gb: 20`, `schedule_time: "23:00"`, `task_name: "EDGAR-SENTINEL\\daily update"`, `distro: Ubuntu`)
- [X] T004 [P] Save public SEC files as fixtures in tests/fixtures/sec/: two Form 4 full submissions (an open-market purchase with footnotes; a 2023+ schema with the 10b5-1 checkbox), one Form 3, one Form 4/A, an excerpt of `master.20261028.idx` (about 30 rows including Form 4, Form 3, 8-K and 10-Q), and the `-index-headers.html` of an 8-K (items 2.02 and 9.01) and of a 10-Q

---

## Phase 2: Foundational (blocks every story)

- [X] T005 Add `store_gz(paths, book, source, rel, key, data, url)` (gzip with `mtime=0`, then `store_bytes`) and `read_stored(paths, entry) -> bytes` (checks the file's size and SHA-256 against its manifest line, decompresses `.gz`, raises `ManifestError` on a mismatch) to src/sentinel/raw/manifest.py; tests in tests/unit/test_manifest.py (the same bytes give an identical file; a changed file is refused)
- [X] T006 Create the fetcher registry in src/sentinel/raw/__init__.py (`FetchReport` with `source`, `status` in {`fetched`, `nothing_new`, `failed`, `skipped: plan ended`}, `requests`, `files_stored`, `bytes`, `latest_date`, `errors`; `FETCHERS: dict[str, callable]`) and the command `sentinel fetch <source> [--from DATE] [--to DATE] [--full-missing] [--window-days N] [--quarterly]` in src/sentinel/cli.py per contracts/cli.md (exit 0 done, nothing new or plan ended; 1 failed; 2 unknown source; 3 a missing `.env` key); test in tests/test_cli.py
- [X] T007 Create src/sentinel/raw/sec.py with the shared SEC client (`sec_client(p)`: `SEC_USER_AGENT` from `.env` or `ConfigError`; `RateLimiter` at `sec.document_requests_per_second`, never above `http.SEC_RPS_CEILING`; `RetryPolicy.from_settings`), `filing_days(start, end)` (weekdays) and `index_url(day)`; test the rate ceiling in tests/unit/test_raw_sec.py
- [X] T008 Change price staging in src/sentinel/staging/prices.py to the newest-file rule of data-model.md: Yahoo files are `history` (`yahoo/*.parquet`, `yahoo/panel/*.parquet`, `yahoo/history/<date>/*.parquet`) or `window` (`yahoo/daily/<date>/batch-*.parquet`, long format with a `ticker` column); Tiingo files are `history` (`tiingo/{prices,panel_prices,listed_prices}/*.csv.gz`, `tiingo/history/<date>/*.csv.gz`) or `window` (`tiingo/daily/<date>/*.csv.gz`); add `file_kind` and `fetched_at` (from the manifest) to `stg_yahoo.price` and `stg_tiingo.price`; per (ticker, session) keep the row of the newest file among the history files and the window files fetched after the ticker's newest history file; tests in tests/unit/test_staging_sources.py (a window adds a session; a newer window replaces a revised session; a newer history file supersedes older windows and histories)

**Checkpoint**: settings, storage helpers, the fetch command and the price staging rule exist; stories can start.

---

## Phase 3: User Story 1 — Every dataset reaches the latest trading day (P1) 🎯 MVP

**Goal**: one refresh brings prices, the calendar, filings, financial values, short volume and the market and economic series to the latest day each provider has published (insider filings: US4).

**Independent Test**: run the fetches and rebuild after a US close; `app.freshness` shows each dataset's latest date equal to its provider's latest published day, and the calendar ends on the last completed session (quickstart §1).

### Tests for User Story 1

- [X] T009 [P] [US1] tests/unit/test_raw_sec.py: the master-index parser on the fixture; `fetch_index` stores `sec/index/<YYYY>/master.<day>.idx.gz` (source `sec_index`, key `master/<day>`) and treats 403/404 as "not published yet" (no file, retried next run); headers are fetched only for `sec.detail_forms` of company-like CIKs, `companyfacts` only for `sec.periodic_forms` filers (once per CIK and day), submissions documents only for CIKs not in `stg_sec_filings.filer` (respx)
- [X] T010 [P] [US1] tests/unit/test_raw_yahoo.py: with a stand-in for `yfinance.download`, the window fetch stores one long-format file per batch of `prices.yahoo_daily_batch_size` (`yahoo/daily/<date>/batch-<NNN>.parquet`, key `daily/<date>/<NNN>`) covering the latest SEC list's symbols plus SPY and IWM; symbols without data go to the failures file; a second run the same day stores nothing
- [X] T011 [P] [US1] tests/unit/test_raw_tiingo.py: new days are asked from the day after each ticker's last staged session and stored at `tiingo/daily/<date>/<T>.csv.gz`; outside `[tiingo.paid_from, tiingo.paid_until)` no request is made and the report says `skipped: plan ended`; the API token never appears in a manifest URL or log line (respx)
- [X] T012 [P] [US1] tests/unit/test_raw_market.py: FRED stores `fred/<SERIES>-<mode>-<date>.json.gz` with no API key in the URL; Cboe stores `cboe/VIX_History-<date>.csv.gz`; FINRA stores `finra/short_volume/<FACILITY>/<day>.txt.gz` for days after the newest stored one and records 403/404 in `absent.csv`; the SEC list is stored once a day (respx)
- [X] T013 [P] [US1] tests/unit/test_staging_sec_daily.py: index rows of company-like CIKs become `stg_sec_filings.filing` rows with `origin = 'daily'`; a bulk row wins for the same accession; header `items` and `period_of_report` fill `items` and `report_date`; `stg_sec_xbrl.fact` takes each company's facts only from its newest document (bulk zip or per-company file)
- [X] T014 [P] [US1] tests/unit/test_reference.py: `build_calendar` raises `db.StepFailed` naming both dates when SPY's last session is older than the newest session reached by at least 1,000 tickers in the staged prices

### Implementation for User Story 1

- [X] T015 [US1] Port v1's ticker-list fetch (`git show v1-final:src/sentinel/ingest/sec_reference.py`) into src/sentinel/raw/sec.py as `fetch_tickers`: once per day, `sec/reference/company_tickers_exchange_<YYYYMMDD>.json` (source `sec_company_tickers`, key `<YYYYMMDD>`)
- [X] T016 [US1] Implement `fetch_index` and `fetch_daily` in src/sentinel/raw/sec.py per research R2, R4 and R5: for each filing day from the day after the newest stored index to yesterday (or `--from`/`--to`), store the master index; for rows whose CIK is company-like (`ref.company`, read-only) and whose form is in `sec.detail_forms`, fetch the header with v1's URL patterns (`sec.headers_url_pattern`, fallback `sec.headers_fallback_url_pattern`) into `sec/headers/<YYYY>/<accession>.txt` (source `sec_filing_header`); for filers of `sec.periodic_forms`, fetch `companyfacts` into `sec/companyfacts/<date>/CIK<10 digits>.json.gz` (source `sec_companyfacts_cik`, key `<cik>/<date>`); for CIKs not in `stg_sec_filings.filer`, fetch the submissions document into `sec/submissions/<date>/CIK<10 digits>.json.gz` (source `sec_submissions_cik`)
- [X] T017 [US1] Port v1's bulk download (`sec_company.py`) into src/sentinel/raw/sec.py as `fetch_bulk`: new copies at `sec/company/<date>/submissions.zip` and `sec/company/<date>/companyfacts.zip` (keys `submissions/<date>`, `companyfacts/<date>`), streamed with `stream_to_file`
- [X] T018 [P] [US1] Create src/sentinel/raw/yahoo.py porting v1's `download` (`git show v1-final:src/sentinel/ingest/yahoo.py`: batches, retries, the failures file) as `fetch_window` (start = today − `prices.yahoo_window_days`, batches of `prices.yahoo_daily_batch_size`, long-format files per research R6) and `fetch_history` (full history from `prices.history_start` into `yahoo/history/<date>/<T>.parquet`, key `history/<T>/<date>`); the universe is the latest `stg_sec_tickers.snapshot` symbols (`.` and `/` written `-`) plus `prices.reference_symbols`
- [X] T019 [P] [US1] Create src/sentinel/raw/tiingo.py porting v1's client (`git show v1-final:src/sentinel/ingest/tiingo.py`; token in the `Authorization` header only) as `fetch_new_days` for the listed companies priced from Tiingo (`ref.security`: source `tiingo`, `listed`), from the day after each ticker's last staged session, into `tiingo/daily/<date>/<T>.csv.gz` at `tiingo.requests_per_second`; outside the paid window return `skipped: plan ended` without any request (`config.in_tiingo_window`)
- [X] T020 [P] [US1] Create src/sentinel/raw/market.py porting v1's `fred.py`, `cboe.py` and `finra_short.py` (`git show v1-final:src/sentinel/ingest/…`): FRED market and first-release modes from `risk_params.sources` into `fred/<SERIES>-<mode>-<date>.json.gz`; Cboe's VIX history into `cboe/VIX_History-<date>.csv.gz`; FINRA short volume per facility and trading day after the newest stored day, with `absent.csv`
- [X] T021 [US1] Register `sec-tickers`, `sec-daily`, `sec-bulk`, `yahoo`, `tiingo`, `fred`, `cboe`, `finra` and `all` (every source except `sec-bulk`, one thread per source, each within its own limits) in src/sentinel/raw/__init__.py
- [X] T022 [US1] Extend src/sentinel/staging/sec_filings.py per data-model.md: add `origin` (`bulk`/`daily`) to `stg_sec_filings.filing`; read the newest bulk `submissions.zip` (by manifest `fetched_at`) as the base; add rows from the stored master indexes for company-like CIKs (cik, accession, form, filing_date) whose accession the base lacks, with `report_date`, `items` and the acceptance time from `stg_sec_headers.header` when present; add `filer` rows from the per-CIK submissions documents (newest per CIK)
- [X] T023 [US1] Extend the header parser in src/sentinel/staging/sec_headers.py with `items` (each `ITEM INFORMATION:` description mapped to its 8-K item code, e.g. "Results of Operations and Financial Condition" → `2.02`, "Financial Statements and Exhibits" → `9.01`, using the SEC's full 8-K item list 1.01–9.01; an unknown description is kept as text) and `period_of_report` (`CONFORMED PERIOD OF REPORT`); add both columns to `stg_sec_headers.header`; tests with the T004 fixtures in tests/unit/test_staging_sec_headers.py
- [X] T024 [US1] Make src/sentinel/staging/sec_xbrl.py read the newest bulk `companyfacts.zip` plus the per-company files `sec/companyfacts/<date>/CIK*.json.gz` newer than it, taking each company's facts only from its newest document
- [X] T025 [US1] Make src/sentinel/staging/market.py read the compressed copies (`.json.gz`, `.csv.gz`) of FRED and Cboe alongside the existing uncompressed ones, newest per series as today
- [X] T026 [US1] Add the calendar guard of research R9 to `build_calendar` in src/sentinel/reference/build.py (the condition tested in T014)
- [X] T027 [US1] Add `app.freshness` to `TABLES` in src/sentinel/serving/publish.py: one row per dataset (`prices`: max session of `core.price_daily`; `filings`: max filing date of `core.filing`; `financial_values`: max `filed` of `core.financial_fact`; `insider_filings`: max filing date of `core.insider_filing`; `short_volume`; `vix`; each FRED series) with `latest_date`
- [ ] T028 [US1] Real one-off refresh (quickstart §1 without the Yahoo full histories and Form 4s): `sentinel fetch sec-tickers`, `sec-bulk`, `sec-daily --from 2026-10-23`, `yahoo`, `tiingo`, `fred`, `cboe`, `finra`; `sentinel build` staging, reference, core, features, labels; `sentinel publish`; `sentinel export`; results checked in tests/real/test_named_cases.py (T029)
- [ ] T029 [US1] Named real checks in tests/real/test_named_cases.py: the calendar ends on the last completed weekday session (not 23 October); Apple (CIK 320193) has a close on that day; `app.freshness` has a row for every dataset

**Checkpoint**: everything except insider filings is current; quickstart §1's freshness checks pass.

---

## Phase 4: User Story 2 — Prices for every listed company a source has (P1)

**Goal**: every SEC-listed symbol asked of Yahoo; renamed companies priced from their listed ticker; price-only stocks with the history their sources hold; a coverage report with reasons.

**Independent Test**: `core.price_coverage` and the named checks of T036 (quickstart §1).

### Tests for User Story 2

- [X] T030 [P] [US2] tests/unit/test_core_prices.py: a listed company whose Tiingo name differs (renamed) is priced from its SEC-listed ticker on dates alone; a price-only company's history starts at its ticker's listing start (the Tiingo listing entry reaching today), not 400 days before the SEC list's date; a symbol another CIK used until day D starts the current owner's history on D + 1; `core.price_coverage` gives the reasons `priced`, `no data in any source`, `rejected: <check>`, `listed after the calendar's end`, and `tiingo_only`

### Implementation for User Story 2

- [X] T031 [US2] Add `--full-missing` to the Yahoo fetch in src/sentinel/raw/yahoo.py: `fetch_history` for every symbol of the latest SEC list with no Yahoo file and not in the failures file
- [X] T032 [US2] In `build_candidates` in src/sentinel/core/prices.py: mark candidates whose ticker is the company's own ticker in the latest SEC list (`own_listed`), set their identity `ok` when the series reaches today's listing period, and add `listing_start` (the start date of the Tiingo listing entry for the ticker whose end date is empty or today; else the series' first session) per research R12
- [X] T033 [US2] In `build_choice` in src/sentinel/core/prices.py: for listed companies, `trim_from` = the latest of `prices.history_start`, `listing_start` and the day after the last day another CIK used the symbol (`ref.ticker_history` of other CIKs; Tiingo listing entries that ended earlier); keep the 400-day warm-up for companies not listed today
- [X] T034 [US2] Add `build_coverage` to src/sentinel/core/prices.py writing `core.price_coverage` (one row per listed company, funds and blank-check companies excluded: `cik`, `ticker`, `filer_type`, `source` in {yahoo, tiingo, none}, `reason`, `priced_from`, `tiingo_only`), register it as `price_coverage` in `CORE` in src/sentinel/build.py after `security`, and echo the counts by reason
- [ ] T035 [US2] Real run: `sentinel fetch yahoo --full-missing`; `sentinel build staging --only yahoo`; rebuild reference, core, features, labels; publish; export; results checked in tests/real/test_named_cases.py (T036)
- [ ] T036 [US2] Named real checks in tests/real/test_named_cases.py: Hitachi (47710) priced from 2012-04-27 or earlier; Deutsche Telekom (946770) from 2010-06-21 or earlier; Standard Life (1370418) and NGK Spark Plug (1442655) priced; at least 450 price-only listed companies with prices before 2025; every SEC-listed symbol stored by Yahoo or in its failures file; every unpriced listed company has a reason

**Checkpoint**: SC-002 and SC-003 met; prices complete for what the sources hold.

---

## Phase 5: User Story 3 — A daily update that matches a full rebuild (P1)

**Goal**: `sentinel update` fetches only what is new, stages it, rebuilds every layer, publishes, records what changed, and equals a full rebuild; a rerun changes nothing; missed days are caught up.

**Independent Test**: tests T037–T039, then quickstart §2 and §3 on real data.

### Tests for User Story 3

- [X] T037 [P] [US3] tests/unit/test_update.py with synthetic raw files (builders added to tests/conftest.py next to `build_world`): (a) an update after adding day D's files equals a full rebuild from the same files (every table's row count and checksum); (b) a second update has status `nothing_new` and every `app` table 0 added, 0 changed, 0 removed; (c) two missed days are caught up in order; (d) a source that raises leaves the others and marks the run `partial`; (e) a second update while `data/.update.lock` holds a live pid stops with that pid in the message; a lock of a dead pid is replaced; (f) less than `update.min_free_gb` free stops before fetching
- [X] T038 [P] [US3] tests/unit/test_truncation.py: build the features from the synthetic world, then again with every record dated after day D removed; every feature row with `as_of <= D` is identical (constitution I)
- [X] T039 [P] [US3] tests/unit/test_raw_yahoo.py and tests/unit/test_raw_tiingo.py: a window with a split or dividend after a symbol's newest history file triggers `fetch_history` for that symbol only; Tiingo the same for `splitFactor` ≠ 1 or `divCash` ≠ 0

### Implementation for User Story 3

- [X] T040 [US3] Event refetch (FR-019) in src/sentinel/raw/yahoo.py and src/sentinel/raw/tiingo.py: after a window fetch, symbols whose window has `Stock Splits` ≠ 0 or `Dividends` ≠ 0 (Tiingo: `splitFactor` ≠ 1 or `divCash` ≠ 0) on a session after their newest history file get `fetch_history`
- [X] T041 [US3] Create src/sentinel/update/record.py: the `ops` tables of data-model.md (`ops.update_run` with `status` in {started, fetching, staging, building, publishing, complete, partial, nothing_new, failed}; `ops.update_source`; `ops.update_table`; `ops.coverage` with `kind` `listed` and `year`; `ops.staged_file`); `checksum(con, table)` = (row count, XOR of row hashes, order-independent); the keyed diff of each `app` table between `serving.prev.duckdb` and `serving.duckdb` (keys: `stock` cik; `price_daily` cik, session; `company_card` cik; `financials` cik, item, period_start, period_end; `filings` accession; `insider_activity` accession, side; `insider_feed` cik, cluster_date, grp; `screener` cik; `freshness` dataset); the log writer `data/logs/update-<date>.log`
- [X] T042 [US3] Incremental staging in src/sentinel/update/run.py: map each manifest source to its staging step; re-stage only the sources with stored files not yet in `ops.staged_file`; the quarterly Form 4 sets, the bulk submissions and the bulk companyfacts re-stage only when a new base file arrived; record the applied files in `ops.staged_file`
- [X] T043 [US3] Implement `update(p, scheduled=False, fetch=True)` in src/sentinel/update/run.py per contracts/cli.md: take the lock (pid in `data/.update.lock`, a dead pid's lock replaced); refuse below `update.min_free_gb`; record `started`; `fetch all` (skipped with `fetch=False`); incremental staging; `build.run` for reference, core, features and labels; copy `serving.duckdb` to `serving.prev.duckdb`; publish; export; diff and checksums; set the status (`complete`; `partial` when a source failed; `nothing_new` when no file was stored and every checksum is unchanged; `failed` on an error, leaving the previous serving copy and export); write the log; release the lock
- [X] T044 [US3] Add `sentinel update [--scheduled] [--no-fetch]` to src/sentinel/cli.py (exit 0 `complete` or `nothing_new`; 1 `partial` or `failed`; 3 configuration)
- [X] T045 [US3] Create src/sentinel/update/verify.py and `sentinel verify [--keep]` in src/sentinel/cli.py: rebuild staging through labels into `data/verify.duckdb` from the stored files, compare every table's checksum with `data/sentinel.duckdb`, print the tables that differ, exit 0 when identical and 1 otherwise; delete the scratch database unless `--keep`
- [ ] T046 [US3] Real run: `sentinel update`; a second `sentinel update` (expect `nothing_new`); `sentinel verify` (expect identical); compare the update's duration in data/logs/update-<date>.log with SC-004's 30 minutes and report the three results

**Checkpoint**: SC-004, SC-005 and SC-006 checked on real data.

---

## Phase 6: User Story 4 — Insider trades the day after they are filed (P2)

**Goal**: Form 3, 4 and 5 filings fetched daily from their full submissions, parsed into the data sets' columns, used by the insider tracker the evening after filing, and reconciled with the quarterly data sets.

**Independent Test**: T047, T048, the reconciliation on a past quarter (T053) and a recent Form 4 in the tracker (T054).

### Tests for User Story 4

- [X] T047 [P] [US4] tests/unit/test_staging_form4_daily.py: parsing the T004 fixtures gives every table of `staging.sec_form4.TABLE_SPECS` with the same lower-cased columns and types (`aff10b5one` from `aff10b5One`; `rptowner_relationship` from `isDirector`, `isOfficer`, `isTenPercentOwner`, `isOther` written as in the data sets, e.g. `Director,Officer`; officer title; non-derivative and derivative lines with their footnote ids in the `_fn` columns; holdings; footnotes; signatures), plus `accepted_at_et` from `ACCEPTANCE-DATETIME`; an element that cannot be converted goes to `stg_sec_form4_daily.parse_issue`
- [X] T048 [P] [US4] tests/unit/test_core_insider.py: an accession present in a quarterly data set is taken from it; a daily-only accession is used, with `known_at` the filing day when accepted before 16:00 on a session and the next session otherwise; differing versions appear in `core.form4_reconciliation`

### Implementation for User Story 4

- [X] T049 [US4] Add `fetch_ownership` to src/sentinel/raw/sec.py and register `form4` in src/sentinel/raw/__init__.py: for each filing day's stored master index (fetching it if missing), every `sec.ownership_forms` row's full submission (`sec.filing_text_url`) stored at `sec/form4/<YYYY>/<accession>.txt.gz` (source `sec_ownership_filing`, key the accession); `--quarterly` ports v1's quarterly data-set download (`sec_bulk.py`)
- [X] T050 [US4] Create src/sentinel/staging/sec_form4_daily.py: parse each stored submission's header (`ACCEPTANCE-DATETIME`, `FILED AS OF DATE`, `CONFORMED SUBMISSION TYPE`) and its `ownershipDocument` XML (standard library `xml.etree.ElementTree`) into `stg_sec_form4_daily.*` with exactly the columns and types of `staging.sec_form4.TABLE_SPECS` plus `accepted_at_et`, `filing_day` and `raw_file`; conversion failures to `stg_sec_form4_daily.parse_issue`; register `sec_form4_daily` in `STAGING` in src/sentinel/build.py
- [X] T051 [US4] In src/sentinel/core/insider.py: read the union of `stg_sec_form4.*` and `stg_sec_form4_daily.*`, an accession held by any quarterly data set excluding its daily rows; `known_at` from the header acceptance time, else the daily submission's `accepted_at_et`
- [X] T052 [US4] Add `build_form4_reconciliation` to src/sentinel/core/insider.py writing `core.form4_reconciliation` (accession; which of owners, line counts and total value differ) for accessions in both sources; register it in `CORE` in src/sentinel/build.py
- [ ] T053 [US4] Parser check on real data: `sentinel fetch form4 --from 2026-09-24 --to 2026-09-30` (filings also in `2026q3_form345.zip`); stage; build core; a named check in tests/real/test_named_cases.py that those accessions show no unexplained difference in `core.form4_reconciliation`
- [ ] T054 [US4] Real backfill: `sentinel fetch form4 --from 2026-10-01`; rebuild; a named check in tests/real/test_named_cases.py that a Form 4 from the 28 October index appears in `core.insider_activity` with its owner, role and value

**Checkpoint**: SC-007 met; US1's insider acceptance scenario is complete.

---

## Phase 7: User Story 5 — Runs by itself every weekday, with a log (P3)

**Goal**: a Windows task runs the update on weekday evenings; `sentinel status` shows the runs, freshness and coverage.

**Independent Test**: T055, T056, then two scheduled evenings (quickstart §6).

### Tests for User Story 5

- [ ] T055 [P] [US5] tests/unit/test_schedule.py: the generated task XML has weekday triggers at `update.schedule_time`, `StartWhenAvailable` true, `MultipleInstancesPolicy` `IgnoreNew`, and the action `wsl.exe -d <distro> --cd <repo> -- <uv> run sentinel update --scheduled`; `install` runs `schtasks.exe /Create /TN <task_name> /XML <file> /F`, `remove` `/Delete /TN <task_name> /F`, `show` `/Query /TN <task_name> /V /FO LIST` (subprocess stand-in)
- [ ] T056 [P] [US5] tests/unit/test_status.py: `sentinel status` on synthetic `ops` tables and a synthetic serving copy prints the recent runs, each dataset's latest date and the coverage summary, and never takes the update lock

### Implementation for User Story 5

- [ ] T057 [US5] Create src/sentinel/update/schedule.py (the task XML in UTF-16 per research R13; `install`, `remove`, `show` through `schtasks.exe`; `uv` located with `shutil.which`; `ConfigError` when `schtasks.exe` is unreachable) and `sentinel schedule install|remove|show [--time HH:MM]` in src/sentinel/cli.py
- [ ] T058 [US5] Add `sentinel status [--runs N]` to src/sentinel/cli.py reading `ops.update_run`, `ops.update_source`, `ops.coverage` and `app.freshness`, plus the task's next run from `schedule show` when installed
- [ ] T059 [US5] With the researcher's approval, install the task on this machine (`sentinel schedule install`), confirm `sentinel schedule show` lists the next weekday 23:00 run, and after the next scheduled evening confirm the run with `sentinel status`, as in specs/001-daily-data-refresh/quickstart.md §6; report the results

**Checkpoint**: SC-008 under way (two weeks of runs).

---

## Phase 8: Polish & cross-cutting

- [ ] T060 [P] Update docs/architecture.md: the daily raw layout (link to specs/001-daily-data-refresh/contracts/raw-layout.md), the staging newest-file rule, `stg_sec_form4_daily`, the `ops` schema, `app.freshness`, and `sentinel fetch`, `update`, `status`, `verify`, `schedule` under Commands
- [ ] T061 [P] Log decisions in docs/decisions.md: V2-16 daily SEC data through the master index, Form 4s from their full submissions; V2-17 Yahoo and Tiingo windows with full refetches after splits and dividends; V2-18 a listed company's own ticker accepted on dates, history from the ticker's listing start; V2-19 the update rebuilds the layers above staging in full, checked by `sentinel verify`; V2-20 Windows Task Scheduler for the schedule
- [ ] T062 [P] Update docs/plan.md (status of steps 1 and 6) and README.md (the daily commands)
- [ ] T063 Run quickstart.md end to end and `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest -q`; report durations and results
- [ ] T064 Mark this file's tasks done in specs/001-daily-data-refresh/tasks.md, merge `001-daily-data-refresh` into `main`, delete the branch locally and on GitHub, and comment on issues #63 and #68

---

## Dependencies & Execution Order

### Phase dependencies

- Setup (Phase 1) → Foundational (Phase 2) → stories.
- **US1** needs Phase 2. **US2** needs US1's Yahoo fetcher (T018) and staging (T008). **US3** needs US1's
  fetchers (T015–T021). **US4** needs the SEC client and index fetch (T007, T016). **US5** needs US3's
  update and `ops` tables (T041–T044).
- Polish needs the stories it documents.

### Story order

US1 → (US2 and US4 in parallel) → US3 → US5. US3 can start once US1 is done; it does not need US2 or
US4, but its real run (T046) is most useful after them.

### Within each story

Tests first (they fail), then fetchers, then staging, then core and serving, then the real run and
its named checks.

### Parallel opportunities

- Setup: T002, T003, T004.
- US1: tests T009–T014 together; fetchers T018, T019, T020 together (different files).
- US2 and US4 can run side by side after US1 (different files: core/prices.py vs
  staging/sec_form4_daily.py and core/insider.py).
- US5: T055, T056 together.
- Polish: T060, T061, T062 together.

## Parallel Example: User Story 1

```text
Task: "T010 [P] [US1] tests/unit/test_raw_yahoo.py …"
Task: "T011 [P] [US1] tests/unit/test_raw_tiingo.py …"
Task: "T012 [P] [US1] tests/unit/test_raw_market.py …"
Task: "T018 [P] [US1] Create src/sentinel/raw/yahoo.py …"
Task: "T019 [P] [US1] Create src/sentinel/raw/tiingo.py …"
Task: "T020 [P] [US1] Create src/sentinel/raw/market.py …"
```

## Implementation Strategy

### MVP first

Setup, Foundational, then US1: every dataset except insider filings current again. Stop and check
quickstart §1's freshness. This already fixes the calendar stopping on 23 October.

### Incremental delivery

1. US1: current data (MVP).
2. US2: complete prices (Yahoo for every listed symbol, renamed and price-only companies).
3. US4: insider filings current.
4. US3: one command does it all, equal to a full rebuild.
5. US5: it runs by itself.

Each step is committed on the feature branch with its tests; the branch is merged into `main` at
T064.

## Notes

- [P] tasks touch different files and depend on no unfinished task.
- Real-data runs (T028, T035, T046, T053, T054) need nothing else to hold `data/sentinel.duckdb` open.
- Never commit `data/`; never put a key in a URL, manifest line or log.
- Tiingo requests only before 26 November 2026.
