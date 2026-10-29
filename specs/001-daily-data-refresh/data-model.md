# Data model: Daily data refresh

Phase 1 of [plan.md](plan.md). What this feature adds to or changes in each layer of
`docs/architecture.md`. Decisions behind it: [research.md](research.md) (R-numbers).

## Layer 1: raw files

Every stored file has one manifest line (`raw/manifest.py` `ManifestEntry`: path, source, key,
role `original`, URL without secrets, fetch time, bytes, SHA-256, HTTP validators, tool). Text
answers are stored gzip-compressed with `mtime=0` (decompressing gives the bytes received). Daily
files live under `<source>/daily/<YYYY-MM-DD>/` where `<YYYY-MM-DD>` is the fetch day. The full
layout per source is in [contracts/raw-layout.md](contracts/raw-layout.md).

## Layer 2: staging

Staging stays a deterministic function of the stored files: for each source, a **base** plus newer
files, the newest file winning per key. Built at once or file by file, the result is the same (R10).

| Table | Change | Key | Newest-wins rule |
|---|---|---|---|
| `stg_sec_form4_daily.submission`, `reportingowner`, `nonderiv_trans`, `nonderiv_holding`, `deriv_trans`, `deriv_holding`, `footnotes`, `owner_signature` | **new**: the quarterly data sets' columns, parsed from each Form 3/4/5 submission (R3), plus `accepted_at_et` (submission only), `filing_day` and `raw_file` | accession (+ the table's line key) | one file per accession; a later file for the same accession (rare) replaces it |
| `stg_sec_form4_daily.parse_issue` | **new**: documents or elements that could not be parsed (accession, element, message) | accession | rebuilt with the tables |
| `stg_sec_filings.filing` | adds `origin` (`bulk` / `daily`); daily rows from the master index of company-like filers, with `report_date`, `items` and the acceptance time from the header where fetched (R4) | accession | bulk rows win for accessions the newest bulk file holds; daily rows fill the rest |
| `stg_sec_filings.filer` | adds rows for CIKs first seen in a daily index (their submissions document, fetched once) | cik | newest document per CIK |
| `stg_sec_headers.header` | adds `items` (8-K items) and `period_of_report`; daily headers appended | accession | one header per accession; the first stored wins |
| `stg_sec_xbrl.fact` | facts per company from the newest `companyfacts` document: the bulk zip or a later per-company file (R5) | (cik, document) | newest document per company |
| `stg_sec_tickers.snapshot` | one snapshot per fetch day (already supported) | (snapshot_date, cik, ticker) | none: all snapshots kept |
| `stg_yahoo.price` | adds `file_kind` (`history` / `window`) and `fetched_at`; daily window files (R6) | (ticker, session) | per ticker, the newest `history` file is the base; `window` files newer than it add or replace sessions after its first day |
| `stg_tiingo.price` | same as Yahoo (R7) | (ticker, session) | same |
| `stg_market.short_volume` | new days appended (R8) | (session, symbol) | one file per facility and day |
| `stg_market.fred`, `stg_market.vix` | unchanged: newest copy per series | (series, period) | newest file |

**Validation rules**

- A Form 4 parse must give every table the quarterly data sets give, with the same column types; an
  element that cannot be converted goes to `parse_issue`, never silently to null.
- A price file that is not a price table (Tiingo's `[]`, an empty Yahoo frame) is counted and
  skipped, as today.
- Staging fails loudly when a stored file is missing or its checksum differs from the manifest.

## Layer 3: reference and core

| Table | Change |
|---|---|
| `ref.calendar` | unchanged rule (SPY's sessions); now extended daily. The update checks that its last day is not older than the newest session in the day's price files (R9). |
| `ref.ticker_history` | unchanged rule; the daily SEC snapshots date tickers from their first to their last appearance. |
| `core.price_candidate` | a listed company's own ticker (from the latest SEC list) is accepted from either source on dates alone (R12); new column `listing_start` (the start of the ticker's current listing). |
| `core.price_choice` | `trim_from` for listed companies: the latest of 2010-01-01, `listing_start`, and the day after another company last used the symbol; the 400-day warm-up still applies to companies known only from filings (R12). |
| `core.price_coverage` | **new**, one row per listed company (funds and blank-check companies excluded): `cik`, `ticker`, `filer_type`, `source` (yahoo / tiingo / none), `reason` (priced, no data in any source, rejected and why, listed after the calendar's end), `priced_from`, `tiingo_only` (stops updating when the plan ends). |
| `core.insider_filing` and the other `core.insider_*` tables | read the union of `stg_sec_form4` (quarterly) and `stg_sec_form4_daily`: an accession held by a quarterly data set is taken from it; daily rows fill the rest. `known_at` uses the header's acceptance time, then the daily submission's. |
| `core.form4_reconciliation` | **new**: accessions present in both sources whose versions differ (owners, line counts, values), with what differs. |

**State of a ticker listing** (R12): `listed today` (in the latest SEC list) → its history reaches
back to `listing_start`; `gone` (left the list) → as today, Tiingo matched by Form 4 ticker or name
search, 90 days of tail after the last evidence.

## Layer 4–5: features and labels

Unchanged definitions. Each update rebuilds them in full (R10): new month-end and release-eve rows
appear when their day comes, and each company's `latest` row moves to its newest session. Labels
are rebuilt by the registered step, development windows only (spec FR-022).

## Layer 6: serving

| Table | Change |
|---|---|
| `app.freshness` | **new**: one row per dataset (prices, filings, financial values, insider filings, short volume, VIX, economic series): its latest date and the run that brought it; the product shows "data as of". |
| other `app.*` | unchanged definitions, republished each run. |

## Operations (new schema `ops` in the build database)

| Table | One row per | Columns |
|---|---|---|
| `ops.update_run` | run | `run_id`, `trigger` (scheduled / manual), `started_at`, `finished_at`, `status`, `days` (the filing and trading days covered), `raw_bytes_added`, `log_file` |
| `ops.update_source` | run and source | `run_id`, `source`, `status` (fetched / nothing new / failed / skipped: plan ended), `requests`, `files_stored`, `bytes`, `latest_date`, `error` |
| `ops.update_table` | run and table | `run_id`, `table_name`, `rows_before`, `rows_after`, `checksum_before`, `checksum_after`; for `app` tables also `added`, `changed`, `removed` by key |
| `ops.coverage` | run and summary line | `run_id`, `kind` (`listed`: by `filer_type`, `source`, `reason` from `core.price_coverage`; `year`: by `year` and `status` (listed / gone), companies with prices that year, as constitution III asks), `companies` |
| `ops.staged_file` | stored file staged | `source`, `raw_file`, `sha256`, `staged_at`, `rows` (which files staging has applied, so a rerun applies only new ones) |

**Run states**: `started` → `fetching` → `staging` → `building` → `publishing` → one of `complete`,
`partial` (a source failed; the others were used), `nothing_new` (no source had anything new; no
table changed), `failed` (stopped; nothing published). Only `complete`, `partial` and `nothing_new`
leave a new published copy or the old one in place; `failed` always leaves the old one.

**Lock**: `data/.update.lock` holds the running process's id; a second start while it is alive stops
with "an update is already running (pid …)"; a lock left by a dead process is replaced.
