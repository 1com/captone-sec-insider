---
description: "Task list for feature 005: stock lookup"
---

# Tasks: Stock Lookup (Product v1, page 2)

**Input**: Design documents from `specs/005-stock-lookup/` (plan.md, spec.md, research.md, data-model.md, contracts/http.md, contracts/cli.md, quickstart.md)

**Tests**: Requested by the spec (endpoint tests on a synthetic warehouse; one test per presentation rule P6 and P7; SC-002, SC-003, SC-005, SC-007 checks). Test tasks are included and written before or with the code they test.

**Organization**: Tasks are grouped by user story so each story can be built and tested on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US5 from spec.md
- Paths are relative to the repository root. Data steps run under the memory ceiling: `cap` = `systemd-run --user --wait --pipe -p MemoryMax=5G -p MemorySwapMax=1G --working-directory="$PWD"`.

---

## Phase 1: Setup

**Purpose**: package skeleton, static assets, the lookup path

- [X] T001 Create `src/sentinel/api/` with `__init__.py`, `lookup.py`, `queries.py`, `glossary.py`, `app.py`, `templates/` and `static/`, each module with a one-line docstring naming its role (plan.md, Project Structure). Add `lookup: Path` to `Paths` in `src/sentinel/config.py` (`root / "data" / "lookup.duckdb"`) and update `tests/unit/test_config.py` if it lists the fields.
- [X] T002 [P] Vendor HTMX: download `https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js` to `src/sentinel/api/static/htmx.min.js` (once, at development time), keep its licence header, and record the file's SHA-256 and the BSD-2 licence in `specs/005-stock-lookup/research.md` R3. Confirm the package build includes `templates/` and `static/` (hatchling includes package data by default; add an include rule in `pyproject.toml` only if `uv build` leaves them out).
- [X] T003 [P] Write `src/sentinel/api/static/style.css`: readable tables with sticky headers and right-aligned numbers, a narrow-screen layout without horizontal page scroll, light and dark colours via `prefers-color-scheme`, a visible data-as-of bar. No web fonts or external resources.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: the glossary, the builder's skeleton and allow-list, the read-only connection, the app shell, the commands and the test fixture. No user story can start before this phase is done.

- [X] T004 Write `src/sentinel/api/glossary.py` (research R6): `CODES` with a plain-English description for all 20 Form 4 codes (A, C, D, E, F, G, H, I, J, K, L, M, O, P, S, U, V, W, X, Z) and `BLANK_CODE = "No code reported"`; `FORMS` (3, 4, 5, 3/A, 4/A, 5/A); `ROLES` (`ceo_cfo`, `officer`, `director`, `ten_pct`, `other`); `HOLDINGS` (D direct, I indirect); `ACQ_DISP` (A acquired, D disposed); `EVENT_KINDS` (A cluster, B1 solo CEO/CFO, B2 solo officer or director, each with its definition from plan §6.4); `TERMS` (Form 4, CIK, accession number, open-market purchase, 10% owner, indirect holding, signal date, data-as-of); `describe_code(code) -> str`, which never returns a bare code. Wording: short and neutral, e.g. P = "Bought shares on the open market or privately", A = "Received shares from the company (award or grant)", F = "Gave up shares to pay tax or an exercise price", M = "Exercised options (or converted a derivative)".
- [X] T005 [P] Write `tests/unit/test_glossary.py`: every Form 4 code has a description different from the code itself; `describe_code(None)` and `describe_code("")` give "No code reported"; every form type, role, holding type and event kind above has an entry.
- [X] T006 Write the builder's skeleton in `src/sentinel/api/lookup.py` (research R1–R2, data-model.md "Rebuild"): `SOURCES`, the allow-list, exactly `core.filing`, `core.issuer`, `core.transaction`, `core.owner_role`, `core.build_log`, `stg.reportingowner`, `stg.nonderiv_holding`, `stg.footnotes`, `evt.prelim_event`, `evt.prelim_event_member`; `build(paths, params) -> LookupReport`, which attaches the warehouse read-only, writes `data/lookup.duckdb.part` with `memory_limit = warehouse.MEMORY_LIMIT` and 4 threads, creates schema `lookup`, then renames the file over `data/lookup.duckdb` only when every table is written (a failed build keeps the previous file); `lookup.meta` with one row: `data_as_of` (newest `core.filing.filing_date`), `dataset` (newest `core.filing.quarter`), `built_at` (UTC), `warehouse_built_at` (newest `core.build_log.finished_at`). Missing source tables raise `warehouse.MissingInput` naming the step to run. Each later table is a separate function called by `build`, so stories add theirs.
- [X] T007 [P] Write the connection and meta query in `src/sentinel/api/queries.py` (research R4): `open_lookup(paths)` opens `data/lookup.duckdb` read-only with `memory_limit = warehouse.MEMORY_LIMIT` and `threads = 4`; `meta(cur)` returns `{"date", "dataset", "built_at", "warehouse_built_at"}`; `edgar_url(issuer_cik, accession)` returns `https://www.sec.gov/Archives/edgar/data/{issuer_cik}/{accession without dashes}/`.
- [X] T008 Write the app shell in `src/sentinel/api/app.py` and `src/sentinel/api/templates/base.html` (contracts/http.md): `create_app(paths) -> FastAPI` with `docs_url=None` and `redoc_url=None` (the default docs load scripts from a CDN; `/openapi.json` stays); one read-only connection opened at start-up and closed at shutdown; a dependency yielding a fresh `cursor()` per request; Jinja2 templates; `/static` mounted; `base.html` shows the data-as-of bar ("Data as of 30 Sep 2026 · SEC data set 2026 Q3") and a glossary link on every page (rule P6); handlers that render 404 and 400 as plain-English pages for HTML routes and as `{"detail": …}` for `/api/` routes; a helper that wraps every JSON body with `data_as_of`.
- [X] T009 Add `sentinel lookup` and `sentinel serve [--port 8766] [--host 127.0.0.1]` to `src/sentinel/cli.py` (contracts/cli.md): `lookup` runs `api.lookup.build`, prints row counts and the data-as-of date, exits 3 on `MissingInput`; `serve` exits 3 if `data/lookup.duckdb` is missing ("run `sentinel lookup` first"), exits 1 naming the port if it is in use, warns when `core.build_log`'s newest `finished_at` in the warehouse is later than `lookup.meta.warehouse_built_at`, then runs uvicorn with `create_app(paths)`. Neither command uses the network. Add a CLI help test to `tests/unit/test_cli.py` if that file checks the command list.
- [X] T010 Add a `lookup_client` fixture to `tests/conftest.py`: with `archives` and `pipeline(until="prelim")`, build a synthetic warehouse with a PayPal-like company (CIK 100, ticker ABC, earlier ticker ABCD): two directors' purchase filings 6 days apart totalling at least $100,000 (one with five trust lines and an untraded direct `holding` row; one with a footnote `note` on the price), a sale (S), an award (A), an option exercise (M), a 4/A amendment, a filing with two joint owners, and an officer promoted to CEO between filings; plus a second company (CIK 200) with no transactions and a third whose name contains the first's name. Add a `build_log` row. Run `api.lookup.build`, and return `TestClient(create_app(tmp_data))`.
- [X] T011 [P] Write `tests/guards/test_lookup_no_prices.py` (SC-005): `lookup.SOURCES` equals the R2 allow-list exactly; the source of `src/sentinel/api/lookup.py` and `queries.py` names no table outside `SOURCES` or `lookup.*` (no `price_`, `evt.event`, `xbrl`, `ff_`, `tiingo`, `session`); after a build, no column in `data/lookup.duckdb` is named `close`, `open`, `high`, `low`, `adj_close`, `volume`, `market_cap`, `addv20` or `dollar_volume`; a write through the app's connection raises.
- [X] T012 [P] Write the base of `tests/unit/test_lookup_build.py`: `lookup.meta` values match the synthetic data; a build that fails part-way leaves the previous `data/lookup.duckdb` unchanged; two builds give identical tables (sorted comparisons).

**Checkpoint**: the app starts on an empty lookup file, every page shows the data-as-of bar, and the guard tests pass.

---

## Phase 3: User Story 1 - Find a company and read its insider transactions (Priority: P1) 🎯 MVP

**Goal**: search by ticker, name or CIK; a company page with every insider transaction in plain English, newest first, in pages, with footnotes and EDGAR links; the two JSON endpoints.

**Independent Test**: with the `lookup_client` fixture, search for the company by ticker, earlier ticker, name and CIK; open its page; every transaction appears with its plain-English description, role at the filing date, reported values, holding type, footnote marker, EDGAR link and the data-as-of line; page 2 and the JSON endpoints return the same rows.

### Tests for User Story 1

- [X] T013 [P] [US1] Extend `tests/unit/test_lookup_build.py`: `lookup.issuer_search` has one row per company in `core.filing`, with every filed name and every normalised ticker with its first and last filing year, the current ticker first; `lookup.transaction` row count equals `core.transaction` and "(accession, line_sk) unique"; owners carry the role as of each filing date (the promoted officer is `officer` before and `ceo_cfo` after); `lookup.footnote` holds only footnotes cited by a transaction.
- [X] T014 [P] [US1] Write `tests/unit/test_api.py` for US1: search by `ABC`, `abcd`, part of the name and `100` (and `0000000100`) finds the company first; a 1-character query shows the hint and gives `400` in JSON; the company page lists transactions newest filing first with the trust lines' date, name, role, shares, price, value, holder and EDGAR link; `?page=2` and an out-of-range page behave as in contracts/http.md; an unknown CIK gives a 404 page and a JSON `404`; the footnote fragment shows the footnote text; HTMX requests (`HX-Request: true`) get fragments and plain requests full pages; JSON fields equal contracts/http.md exactly.
- [X] T015 [P] [US1] Add the presentation-rule tests to `tests/unit/test_api.py`: **P6**: `/`, `/search?q=ABC`, `/company/100`, `/company/100/transactions?page=1` and both JSON endpoints state the data-as-of date and data set; **P7**: on the company page every transaction code appears with its glossary description and no code cell holds a bare code, and every JSON transaction has a non-empty `code_description`.

### Implementation for User Story 1

- [X] T016 [US1] Build `lookup.issuer_search` in `src/sentinel/api/lookup.py` (data-model.md): `name` = `core.issuer.name` when present, else the name on the newest filing; `names` = every distinct `issuer_name` filed; `tickers` = STRUCT(ticker, first_year, last_year)[] from `core.filing.symbol_raw` normalised with `sentinel.core.symbols.normalise` (none for NONE, N/A, blank) plus `core.issuer.tickers`, newest first; `n_transactions`, `first_filing`, `last_filing`.
- [X] T017 [US1] Build `lookup.filing_owner` and `lookup.transaction` in `src/sentinel/api/lookup.py`: owners from `stg.reportingowner` (first quarter wins, as for `core.filing`), role from `core.owner_role` as of the filing date (latest `valid_from ≤ filing_date`, "null role → shown as other"); transactions from `core.transaction` with `owners` as STRUCT(cik, name, role, title)[], inserted sorted by `issuer_cik`, `filing_date desc`, `accession desc`, `line_sk`.
- [X] T018 [US1] Build `lookup.footnote` in `src/sentinel/api/lookup.py`: `stg.footnotes` rows whose (accession, footnote_id) appear in some `core.transaction.fn_ids`; first quarter wins on duplicates.
- [X] T019 [US1] Write the US1 queries in `src/sentinel/api/queries.py` (research R7, R8): `search(cur, q)` (digits → CIK without leading zeros; exact normalised ticker; case-insensitive name contains; order: exact ticker or CIK, then names starting with `q`, then the rest; at most 25); `issuer(cur, cik)`; `transactions_page(cur, cik, page, page_size)` (newest first, total count, `LIMIT/OFFSET`); `footnotes(cur, accession, ids)`.
- [X] T020 [US1] Write the US1 pages in `src/sentinel/api/app.py` with `templates/search.html`, `_results.html`, `company.html`, `_transactions.html`, `_footnotes.html`: `/` (GET form; `hx-get="/search"` with `hx-trigger="keyup changed delay:300ms"`), `/search`, `/company/{cik}` (header with name, CIK and tickers with years; first page of transactions), `/company/{cik}/transactions`, `/filing/{accession}/footnotes`. Each row: trade date, filing date, form with description, owners with roles, code with description (rule P7), acquired or disposed, shares, reported price, value, shares after, direct or indirect with holder, footnote marker (opens the fragment), EDGAR link. A note under the table: "Prices and values are as reported by the filer and can contain errors." Paging links work without JavaScript.
- [X] T021 [US1] Write the JSON routes in `src/sentinel/api/app.py` (contracts/http.md): `GET /api/issuers/search?q=` and `GET /api/issuers/{cik}/transactions?page=&page_size=` (1–500, default 100), with the exact field names of the contract, `data_as_of` on every body, `400` and `404` as specified.

**Checkpoint**: US1 is complete and testable on its own: the lookup answers "what have this company's insiders done?".

---

## Phase 4: User Story 2 - See each insider's holdings over time (Priority: P2)

**Goal**: for each insider, shares held after each filing, summed over all holdings, with the split by holding.

**Independent Test**: in the fixture, the director with five trust lines and an untraded direct holding shows one row on that filing date: direct equal to the untraded holding, indirect equal to the five trust lines' shares after, and their total; joint owners see the same snapshot with "filed jointly with …".

- [X] T022 [P] [US2] Extend `tests/unit/test_lookup_build.py` and `tests/unit/test_api.py`: `lookup.holding` follows research R5 (last line per holding by highest `line_sk`; untraded rows from `stg.nonderiv_holding`; a transaction line wins over a holding row for the same holding; `nature_of_ownership` empty string when null); the insider page sums direct and indirect per filing date and security title; joint filings name the co-filer; an unknown owner gives 404.
- [X] T023 [US2] Build `lookup.holding` in `src/sentinel/api/lookup.py` (data-model.md), key (accession, security_title, direct_indirect, nature_of_ownership), with `source` = `trade` or `holding`.
- [X] T024 [US2] Write `insiders(cur, cik)` (per owner: name, latest role and title, number of filings, first and last filing date) and `holdings(cur, cik, owner_cik)` (per filing date and security title: direct, indirect, total, the per-holding split, co-filers) in `src/sentinel/api/queries.py`.
- [X] T025 [US2] Add the insiders section to `templates/company.html` (`_insiders.html`) and the route `/company/{cik}/insider/{owner_cik}` with `templates/_holdings.html` (fragment for HTMX, full page otherwise) in `src/sentinel/api/app.py`.

**Checkpoint**: US1 and US2 work; holdings put the trades in context.

---

## Phase 5: User Story 3 - See the company's insider-buying events (Priority: P2)

**Goal**: the company's SEC-only events (A, B1, B2) with date, kind, buyers and roles, value and member filings; no outcomes.

**Independent Test**: in the fixture, the two-director purchases form a cluster shown with kind, date, 2 buyers, value and both filings; a company without events shows the empty-state sentence; nothing on the page or in the data is a return, outcome or score.

- [X] T026 [P] [US3] Extend `tests/unit/test_lookup_build.py` and `tests/unit/test_api.py`: `lookup.event` and `lookup.event_member` match `evt.prelim_event` and `evt.prelim_event_member` (with `owner_names` from the member filings); the company page lists the cluster with the plain-English kind; CIK 200 shows "No insider-buying events in the filings"; the event section's fields are only those in data-model.md.
- [X] T027 [US3] Build `lookup.event` and `lookup.event_member` in `src/sentinel/api/lookup.py` (data-model.md), `owner_names` = names on each member filing.
- [X] T028 [US3] Write `events(cur, cik)` (newest first, with members) in `src/sentinel/api/queries.py` and the events section (`templates/_events.html`) on the company page in `src/sentinel/api/app.py`: kind with its description, signal date, number of buyers and their roles, total value, member filings with EDGAR links, and the sentence "The research applies further checks (prices, company type) before an event enters the study." No return, outcome or score field.

**Checkpoint**: US1–US3 work.

---

## Phase 6: User Story 4 - Understand the words (Priority: P3)

**Goal**: a glossary for every term the pages use (rule P7).

**Independent Test**: every code, form type, role, holding type and event kind that appears on the fixture's company page has a glossary entry, and the glossary page shows the data-as-of line.

- [X] T029 [P] [US4] Add to `tests/unit/test_api.py`: `/glossary` lists every entry of `CODES`, `FORMS`, `ROLES`, `HOLDINGS`, `EVENT_KINDS` and `TERMS`; every code and form on `/company/100` has a glossary entry; the glossary shows the data-as-of line.
- [X] T030 [US4] Write the `/glossary` route and `templates/glossary.html` from `src/sentinel/api/glossary.py`, with anchors so code cells on the company page link to their entries.

---

## Phase 7: User Story 5 - Get the same data programmatically (Priority: P3)

**Goal**: the JSON endpoints return exactly what the pages show.

**Independent Test**: for the fixture company, the JSON transactions equal the page's rows, field by field.

- [X] T031 [P] [US5] Add to `tests/unit/test_api.py`: for `/company/100/transactions?page=1` and `/api/issuers/100/transactions?page=1`, the same accessions, line keys, codes, descriptions, owners, values and holders in the same order; the search endpoint and page list the same CIKs; `/openapi.json` lists both endpoints and `/docs` is not served.
- [X] T032 [US5] Make page and JSON share one row-building function in `src/sentinel/api/app.py` (or `queries.py`), so they cannot drift; document both endpoints' fields in their docstrings (shown in `/openapi.json`).

---

## Phase 8: Polish, real run and delivery

- [X] T033 [P] Write `tests/integration/test_lookup_real.py` (`@slow`, skipped when `data/lookup.duckdb` is absent): every `trans_code` in the real `lookup.transaction` has a glossary description (SC-003); the page and JSON for the company with the most lines (about 76,500) respond within 2 s each (SC-002); PayPal (CIK 1633917): the two filings of the 23 Nov 2021 cluster, the event worth $2,287,696.69, and Dorman's holdings of 44,890 before and 46,437 after (SC-007); `PYPL`, `paypal`, `1633917` and `SIVB` searches find the right company first (SC-001).
- [X] T034 Real run: `cap uv run sentinel lookup`; record row counts per table, file size, time and peak memory in `specs/005-stock-lookup/run-notes.md`; run T033 under `cap`; start `uv run sentinel serve`, walk quickstart.md's checks 1–7, and check 20 EDGAR links from different companies (SC-006) at no more than 1 request per second with the SEC User-Agent; record the results.
- [X] T035 [P] Update the docs: `README.md` (`sentinel lookup`, `sentinel serve` and the URL in the command table); `docs/planning/05-user-stories-and-tasks.md` (task 8.1 status) and `docs/planning/README.md` (status table); `docs/initialplan.md` §8.2 (the `lookup.*` tables as a product artifact).
- [X] T036 Run `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check src tests`; all pass. Tick the tasks in `specs/005-stock-lookup/tasks.md`; commit; merge `005-stock-lookup` into `main` and delete the branch after the researcher's approval (keep `gh-pages`).

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup; blocks every user story.
- **US1 (Phase 3)**: after Phase 2. The MVP.
- **US2 (Phase 4)** and **US3 (Phase 5)**: after Phase 2; they need `lookup.filing_owner` from US1's T017 for owner names, so start them after T017 (each is otherwise independent of US1's pages).
- **US4 (Phase 6)**: after Phase 2; its page test needs US1's company page.
- **US5 (Phase 7)**: after US1 (T020, T021).
- **Polish (Phase 8)**: after the stories wanted for delivery; T034 needs the real warehouse.

### Within each story

Tests first (they fail), then the builder table, then queries, then pages and routes.

### Parallel opportunities

- T002 and T003 run alongside T001's module creation.
- T005, T007, T011 and T012 run in parallel after T004 and T006 exist.
- In US1, T013, T014 and T015 are written in parallel; T016, T017 and T018 touch the same file (`lookup.py`) and run in sequence.
- US2 and US3 can run in parallel after T017, in different builder functions and templates.

## Parallel Example: User Story 1

```bash
# Tests for US1, written together:
Task: "T013 lookup tables in tests/unit/test_lookup_build.py"
Task: "T014 routes and paging in tests/unit/test_api.py"
Task: "T015 P6 and P7 rules in tests/unit/test_api.py"
# Then the builder (one file, in order): T016 → T017 → T018; then T019 → T020 → T021
```

## Implementation Strategy

### MVP first (User Story 1)

1. Phases 1–2: skeleton, glossary, builder shell, app shell, commands, fixture, guard tests.
2. Phase 3 (US1): search, transactions, footnotes, JSON.
3. **Stop and validate**: run US1's tests and quickstart checks 1–3 on the real lookup file. This is already a usable lookup.

### Incremental delivery

1. US2 (holdings) and US3 (events), in either order or in parallel.
2. US4 (glossary page) and US5 (page–JSON parity).
3. Phase 8: real-data tests, real run, docs, merge. Target: Wednesday 4 November (planning task 8.1).
