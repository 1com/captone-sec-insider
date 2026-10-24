# Research: Stock Lookup

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-24

Checks run on 2026-10-24 against `data/warehouse.duckdb` (built by features 002 and 004) and the installed environment.

## R1. Serve from a lookup database, not the warehouse

- **Finding**:
  - The warehouse holds market-price tables (`core.price_daily`, `stg.price_tiingo`, `evt.event` with floor values and market caps). Constitution VI forbids serving Yahoo or Tiingo prices, and counts per-security values derived from Tiingo prices as Tiingo data.
  - DuckDB allows one writing process per file, and no writer while another process has the file open. A server holding the warehouse open would block every build step, as `sentinel explore` already does.
  - Transactions per company: median 81 lines, 99th percentile about 3,800, maximum 76,529 (20,899 companies).
- **Decision**: `sentinel lookup` builds `data/lookup.duckdb` from an **allow-list of SEC-derived warehouse tables** (R2). The app opens only that file, read-only. Rows are sorted by company, so one company's rows sit together.
- **Rationale**:
  - No price table exists in the file, so no page can show one (SC-005 holds by construction, and a test checks it).
  - The server never locks the warehouse; builds and the explorer keep working.
  - Sorting by company lets DuckDB skip most of the file for a company page.
- **Alternatives rejected**:
  - **Read the warehouse directly, read-only.** Lock clashes with build steps, and the no-price rule would rest on query discipline alone.
  - **Parquet files per table.** Works, but loses DuckDB's single-file convenience and adds file management for nothing.

## R2. Source tables (the allow-list)

| Lookup content | Warehouse source | Notes |
|---|---|---|
| Companies, names, current tickers | `core.filing` (name as filed, newest first), `core.issuer` (SEC submissions: name, tickers) | `core.issuer` covers only event companies; `core.filing` covers all 20,899 |
| Ticker history | `core.filing.symbol_raw`, normalised as in `sentinel.core.symbols` | First and last filing date per ticker |
| Transactions | `core.transaction` (all forms, all codes) | Reported price and value only |
| Owners and roles | `stg.reportingowner` (names, CIKs per filing), `core.owner_role` (role as of the filing date) | ASOF join on `valid_from ≤ filing_date` |
| Holdings | `core.transaction` (shares after, per holding), `stg.nonderiv_holding` (untraded holdings) | See R5 |
| Footnotes | `stg.footnotes`, only those cited by a transaction (`core.transaction.fn_ids`) | |
| Events | `evt.prelim_event`, `evt.prelim_event_member` | SEC-only definitions (spec Assumptions) |

Nothing else is read. A test fails if the builder's SQL names a table outside this list, and another fails if the lookup file has a column named like a market price (`close`, `open`, `high`, `low`, `adj_close`, `volume`, `market_cap`, `addv20`, `dollar_volume`).

## R3. Web stack

- **Finding**: installed and locked: FastAPI 0.159.1, Starlette 1.9.0, Jinja2 3.1.6, uvicorn 0.54.0, httpx 0.28.1 (for the test client). The constitution names FastAPI, Jinja2 and HTMX (D36).
- **Decision**:
  - FastAPI app in `src/sentinel/api/`, pages rendered with Jinja2, served by uvicorn.
  - **HTMX 2.0.4**, one minified file vendored under `src/sentinel/api/static/` (BSD-2 licence, released December 2024), for search-as-you-type and paging without full reloads. Pages also work without JavaScript: the search is a plain GET form and paging uses links.
  - Plain CSS in one file; no build chain, no fonts or scripts from the internet at run time.
- **Rationale**: the smallest stack the constitution allows (VII); no new Python dependency.
- **Alternatives rejected**: a JavaScript front end (React), Streamlit (D36).

## R4. Connections and concurrency

- **Decision**: one read-only DuckDB connection opened at start-up (memory limit `warehouse.MEMORY_LIMIT`, 4 threads); each request uses its own `cursor()`. Endpoints are synchronous, so FastAPI runs them in its thread pool.
- **Rationale**: DuckDB connections are not thread-safe but cursors are; read-only mode makes writing impossible (FR-013).

## R5. Holdings over time

- **Finding** (feature 002, research R5): holdings are reported per holding (direct, or indirect with a description such as "2021 Family Trust 1"), and a filing can list untraded holdings in `NONDERIV_HOLDING`.
- **Decision**: one snapshot per (filing, security title, holding):
  - traded holdings: `shares_after` of the holding's last line in the filing (highest `line_sk`);
  - untraded holdings: the `NONDERIV_HOLDING` row;
  - if both exist for the same holding, the transaction line wins.
  The page shows, for each insider and security title, one row per filing date: held directly, held indirectly, total, with the split by holding on request.
- **Joint filings**: a snapshot belongs to the filing, so every co-filer on it shows the same figures; the page says "filed jointly with …".
- **Rationale**: the same rule as the study's holdings (F7), applied to every filing, not only clean purchases.

## R6. Transaction codes and glossary

- **Finding**: codes in the data, with counts: S 2,666,067 · A 1,265,020 · M 972,902 · P 867,331 · F 831,902 · J 261,937 · G 190,299 · D 147,711 · C 80,768 · L 20,754 · X 19,798 · I 12,490 · U 11,654 · W 2,866 · Z 1,610 · O 475 · H 66 · E 57 · blank 12. Form types: 4, 3, 4/A, 5, 3/A, 5/A.
- **Decision**: one dictionary in `src/sentinel/api/glossary.py` with a plain-English description for each of the 20 codes in the SEC's Form 4 instructions (the 18 above plus K and V) and for a blank code ("No code reported"), each form type, role, holding type and event kind. A unit test checks the dictionary against the synthetic data, and a slow test against every code in the real warehouse (SC-003).
- **Wording**: short, neutral, no jargon, e.g. P = "Bought shares on the open market or privately", A = "Received shares from the company (award or grant)", F = "Gave up shares to pay tax or an exercise price", M = "Exercised options (or converted a derivative)".

## R7. Search

- **Decision**: a `lookup.issuer_search` table: CIK, current name, all names filed, all tickers with first and last filing year. A query matches:
  - a CIK, when the input is digits (leading zeros ignored);
  - a ticker, exactly (normalised);
  - a name, case-insensitively, anywhere in any filed name.
  Exact ticker and CIK matches come first, then names that start with the input, then the rest; at most 25 results. Inputs under 2 characters return a hint.
- **Rationale**: 20,899 companies fit in memory; a full scan takes milliseconds.

## R8. Paging and speed

- **Decision**: 100 transactions per page, newest filing first (`filing_date desc, accession desc, line_sk`), `LIMIT … OFFSET …`; the total count is shown. The company page loads only the first page, the event list, and one summary row per insider; holdings history loads per insider on request.
- **Check (SC-002)**: the largest company (76,529 lines) is timed in a slow test against the real lookup file.

## R9. Data-as-of (rule P6)

- **Decision**: `lookup.meta` records the newest filing date, the newest SEC data set (`2026q3`), the build time and the warehouse's last build-log entry. Every page shows "Data as of 30 Sep 2026 (SEC data set 2026 Q3)", and every JSON response carries `data_as_of`. `sentinel serve` warns when the warehouse has been rebuilt after the lookup file.

## R10. Port and command

- **Decision**: `sentinel serve` (default port **8766**, `--port` to change; host 127.0.0.1). Port 8000 belongs to another local app and the MVP uses 8765, so both can run together.
- **Correction to the spec**: the spec's assumption named 8765; 8766 avoids the MVP.

## R11. Tests

- **Decision**:
  - Unit tests build a synthetic warehouse with the existing fixtures (`archives`, `pipeline`), run the lookup build, and call the app with FastAPI's `TestClient`.
  - One test per presentation rule: P6 (data-as-of on every page and response) and P7 (every code shown with its description; no bare code).
  - Guard tests: the builder's allow-list (R2), no price-like columns in the lookup file, the app's connection is read-only.
  - Slow tests on the real lookup file: every real code has a description; the largest company's page within 2 s; the PayPal example (SC-007).
