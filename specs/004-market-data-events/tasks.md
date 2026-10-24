---

description: "Task list for feature 004: market data, final events, delistings, company financials and trading costs (plan Steps 7–10)"
---

# Tasks: Market Data, Final Events, Delistings, Company Financials and Trading Costs

**Input**: Design documents from `specs/004-market-data-events/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: included. The constitution's quality gates require them (price tests, point-in-time and truncation tests, data-quality tests), and so do FR-015, SC-006 and SC-008. In each story, write the test tasks first and confirm they fail.

**Organization**: by user story, in the spec's priority order:
- **US1 (P1)**: prices, and the Tiingo register;
- **US2 (P2)**: G8, final events, coverage, the golden set;
- **US3 (P3)**: SEC filing histories and delistings;
- **US4 (P4)**: XBRL facts and market capitalisation;
- **US5 (P5)**: tick-size pilot and costs;
- **US6 (P6)**: French reference data.

The stories read each other's *tables* in the real run, but each is **tested independently**, on synthetic tables built with the T008 helpers.

**Memory**: every real run, slow test and build in this list runs under `systemd-run --user -p MemoryMax=5G -p MemorySwapMax=1G` (the quickstart's `cap`), with DuckDB at `warehouse.MEMORY_LIMIT` and 4 threads. Close `sentinel explore` first.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelisable (different files, no dependency on incomplete tasks)
- **[Story]**: US1–US6. Setup, Foundational and Polish tasks carry no story label.

---

## Phase 1: Setup

- [ ] T001 Confirm the starting point:
  - branch `004-market-data-events` is checked out;
  - `uv run pytest` and `uv run ruff check .` pass;
  - feature 002's header job (`systemctl --user status sentinel-headers`) has finished and loaded `core.filing_header`.
  
  Then finish feature 002's T037:
  - run `uv run sentinel verify-sec`;
  - run `uv run sentinel audit no-sic`, which writes the D45 sheet for the researcher;
  - record the header results in `specs/002-insider-warehouse/run-notes.md`.
- [X] T002 [P] In `pyproject.toml`, move `"yfinance>=1.7,<1.8"` from the `mvp` dependency group to `[project] dependencies`, then run `uv lock` and `uv run python -c "import yfinance, pandas"`.

---

## Phase 2: Foundational (blocks every story)

- [X] T003 Update `config/params.yaml` to `version: 8` exactly as in [contracts/params-rules.md](contracts/params-rules.md):
  - `registered.delisting_returns.value.other_venue_treated_as: performance_nasdaq`, with the register `value` text "0% acquired; −30% NYSE/NYSE American; −55% Nasdaq and other venues; unknown = performance-related";
  - every new `rules` key: `final_detection_start: 2011-07-01`, `price_history_start: 2010-01-01`, `g7_excluded_sic`, `g7_no_sic: exclude`, the two delisting form lists, `delisting_notice_after_months: 12`, `delisting_end_gap_sessions: 5`, `remap_after_days: 90`, `tick_size_usd: 0.01`, `tick_size_pilot_usd: 0.05`, `min_volatility_returns: 40`;
  - every new `ops` key, with `tiingo_paid_until: null` and `market_cap_examples: []`.
- [X] T004 [P] Update `docs/initialplan.md`:
  - **Appendix E**: change the "Delisting returns" row's value to the same text as T003.
  - **§12 decision log**:
    - **D50**: delistings from OTC or unknown venues take the Nasdaq return (−55%). The plan's §6.7 covers only NYSE, NYSE American and Nasdaq; −55% is the more conservative registered value.
    - **D51**: final detection runs from 2011-07-01, a six-month warm-up whose events are never labelled, with prices from 2010-01-01. Unpriced events start cooldowns. G8 is applied per purchase line, and the G6 minimum is re-applied afterwards. Rationale: research R1, R6 and R7.
- [X] T005 Update `src/sentinel/config.py`:
  - **`Paths`** gains `yahoo = data/raw/yahoo`, `tiingo = data/raw/tiingo`, `french = data/raw/french`, `finra = data/raw/finra`, `sec_company = data/raw/sec/company`, `audits_004 = specs/004-market-data-events/audits` and `reports_004 = specs/004-market-data-events`.
  - **`load_params`** enforces the params-rules contract's rules 2–5:
    - `rules.g7_no_sic ∈ {exclude, current_sic}`, and `g7_excluded_sic` is a list of integers;
    - `final_detection_start < registered.labelled_window_start`, and `price_history_start ≤ final_detection_start − 1 year`;
    - `tiingo_paid_until` is null or later than `tiingo_paid_from`;
    - the two delisting form lists are disjoint.
- [X] T006 [P] Extend `tests/unit/test_config.py` and `tests/unit/test_params_register.py`:
  - `version == 8`;
  - every rule in T005, each with a failing example;
  - `check_register` passes with the updated Appendix E row;
  - the new `Paths` fields.
- [X] T007 [P] Create `src/sentinel/core/tiingo_register.py` with:
  - `TIINGO_DERIVED`: (table, predicate) pairs exactly as in [contracts/tiingo-register.md](contracts/tiingo-register.md);
  - `class OutsidePaidWindow(Exception)`;
  - `paid_window_open(params, today) -> bool`, true when `today ≥ ops.tiingo_paid_from` and `ops.tiingo_paid_until` is set and `today < tiingo_paid_until`;
  - `require_paid_window(params, today=None)`.
  
  In `src/sentinel/cli.py`, add the exit code `OUTSIDE_PAID_WINDOW = 6` and map `OutsidePaidWindow` to it.
- [X] T008 [P] Add synthetic builders to `tests/conftest.py`. Fixture data is **synthetic only**: no real Tiingo data is ever committed.
  - `yahoo_frame(rows, splits=…)` returns a DataFrame shaped like `yf.download(auto_adjust=False, actions=True)`, with columns `Open, High, Low, Close, Adj Close, Volume, Dividends, Stock Splits`.
  - `tiingo_csv(rows)` returns text with the header `date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,divCash,splitFactor`.
  - `market(con, issuer, rows, source="yahoo")` writes `core.session`, `core.price_series` (one chosen primary) and `core.price_daily` in the [data-model.md](data-model.md) layout, with as-traded columns and `price_source`.
  - `submissions_zip(...)` and `companyfacts_zip(...)` build small zips with the SEC JSON layout: `filings.recent` arrays plus `files` pages, and `facts.{dei,us-gaap}.{tag}.units.{unit}[{start?, end, val, accn, fy, fp, form, filed}]`.
- [X] T009 In `src/sentinel/warehouse.py`, extend `input_fingerprint` to include the manifest originals of the sources `yahoo`, `tiingo`, `french`, `finra` and `sec_company`, as sorted (source, key, sha256) triples. A rebuild after any new download then shows a new fingerprint in `core.build_log`.

**Checkpoint**: parameters, paths, the Tiingo guard and the test builders are ready.

---

## Phase 3: User Story 1 — Prices for every event company, including those that later disappeared (P1) 🎯 MVP

**Goal**: daily as-traded and adjusted prices, one chosen series per issuer, from Yahoo now and from Tiingo in the paid month, with a deletion register.

**Independent test**: `uv run pytest tests/unit/test_yahoo.py tests/unit/test_tiingo.py tests/unit/test_prices.py tests/unit/test_tiingo_register.py` on synthetic data. Then the slow test T020 on the real Yahoo pull.

### Tests (write first)

- [X] T010 [P] [US1] `tests/unit/test_yahoo.py`, with `yf.download` monkeypatched:
  - Each ticker is stored as `data/raw/yahoo/{ticker}.parquet` with one manifest line: `source = yahoo`, key the ticker, url `yfinance.download(start=2010-01-01, auto_adjust=False, actions=True)`, and the SHA-256 of the file.
  - A rerun skips stored tickers.
  - A batch failing 3 times lists its tickers in `failures.csv`.
  - `universe_tickers` returns Yahoo-mapped tickers of issuers with a preliminary event on or after `rules.final_detection_start`, plus SPY and IWM.
  - The primary ticker is the current ticker most often reported in the issuer's Form 4s, with ties broken alphabetically.
- [X] T011 [P] [US1] `tests/unit/test_tiingo.py`, using respx and synthetic data:
  - `require_paid_window` raises before `tiingo_paid_from`, when `tiingo_paid_until` is null, and on or after `tiingo_paid_until`.
  - The token goes in the `Authorization` header and never appears in a URL or manifest line.
  - **Resolution**:
    - `XYZ` resolves to `XYZQ` when only the `Q` form overlaps;
    - among several matches, the candidate whose interval ends last while overlapping the filing span is primary, and the others are `fill_in`.
  - **Identity check**:
    - `dates` when the meta start–end does not overlap the issuer's filings under the ticker;
    - `name` when no significant word is shared, after dropping *inc, corp, co, ltd, holdings, group, the, class*;
    - `no_data` when the meta start date is null.
  - **Storage**: files go to `data/raw/tiingo/meta/{ticker}.json.gz` and `prices/{ticker}.csv.gz` with `source = tiingo` manifest lines, and a rerun refetches nothing.
  - **Yahoo fallback**: an issuer with no Yahoo file, or whose Yahoo file starts after its first event in the universe, is selected for Tiingo.
- [X] T012 [P] [US1] `tests/unit/test_prices.py` (spec US1 acceptance 1 and 3):
  - **1-for-10 reverse split** (`split_ratio` 0.1): before the split, as-traded close = Yahoo close × 0.1 and as-traded volume = Yahoo volume ÷ 0.1, with equal `dollar_volume`. `cum_split_after` = the product of split ratios after the session.
  - **Tiingo rows** are copied as-traded.
  - **Series choice and `reason`**: `yahoo_primary`, `tiingo_resolved`, `yahoo_starts_late→tiingo`, and an unpriced issuer with no chosen series.
  - **Duplicate sessions in one file**: the last row in file order is kept, and an `audit.price_issue` row is written with `duplicate_session`.
  - **Dropped rows**: rows with `close ≤ 0` or `high < low` are dropped and listed.
  - **`core.session`**: SPY sessions numbered from 1.
  - **Truncation**: `build(cutoff=T)` drops `core.price_daily` rows after the last session on or before T, but not `core.session` rows.
- [X] T013 [P] [US1] `tests/unit/test_tiingo_register.py`:
  - every warehouse table with a `price_source` column is in `TIINGO_DERIVED` (introspect `information_schema.columns` after building fixtures for all stories);
  - `status` counts registered files and rows;
  - `delete(yes=False)` changes nothing;
  - `delete(yes=True)` removes the registered rows, tables and files, rewrites the warehouse file, appends `role = deleted` manifest lines, and leaves W12 satisfied.

### Implementation

- [X] T014 [US1] Implement `src/sentinel/ingest/yahoo.py`: `universe_tickers(con, params)`, `primary_tickers(con)` and `download(paths, params, tickers, limit=None, retry_failures=False, echo=print)`.
  - Batches of `ops.yahoo_batch_size`, with `ops.yahoo_pause_seconds` between them and 3 retries with back-off.
  - Parquet written atomically (`.part` → rename, then `chmod 0o444`).
  - Lines written through `manifest.Manifest`.
  
  Follow feature 003's `mvp/pipeline/prices.py` pattern without importing it.
- [X] T015 [US1] Implement `src/sentinel/ingest/tiingo.py`, with every write guarded by `require_paid_window`:
  - **Client**: an `httpx.Client` with the `Authorization: Token …` header and a generic User-Agent; the SEC contact is never sent. A `RateLimiter` at `ops.tiingo_requests_per_second`.
  - **`store_list`**: stores `supported_tickers.zip` once in `data/raw/tiingo/`.
  - **`resolve(con, index, params)`**: (issuer, ticker, role, list interval, exchange) rows. It reuses `sentinel.core.symbols.match` logic for the `Q` suffix.
  - **`fetch(paths, params, targets, limit, retry_failures)`**: meta, then prices with `startDate = rules.price_history_start` and `format=csv`. Both are gzip-written atomically with manifest lines.
  - **`identity(meta, sec_name, filing_span)`**.
- [X] T016 [US1] Implement `src/sentinel/core/prices.py`: `build(con, paths, params, cutoff=None, issuers=None) -> PriceReport`, creating:
  - **`stg.price_yahoo` and `stg.price_tiingo`**: loaded in chunks of 250 files, each chunk one transaction into a `_new_` shadow table, then swapped. Building `stg.price_tiingo` from files outside the paid window raises `OutsidePaidWindow`.
  - **`core.tiingo_listing`**.
  - **`core.price_series`**: choice rules from research R4.
  - **`core.price_daily`**: as-traded = Yahoo value × `cum_split_after` (volume ÷ it), rounded to 6 decimals; Tiingo raw as-is. Validity: "`close > 0`, `low ≤ high`".
  - **`core.session`**: from SPY.
  - **`audit.price_issue`**.
- [X] T017 [US1] Implement `status(con, paths, params)` and `delete(con, paths, params, yes)` in `src/sentinel/core/tiingo_register.py`, following the contract:
  1. stop if the warehouse lock is held;
  2. delete the registered rows and tables;
  3. `ATTACH` a fresh file, `COPY FROM DATABASE`, compare row counts, replace the file;
  4. delete `data/raw/tiingo/` and any `data/**/*tiingo*`;
  5. append the manifest lines;
  6. verify, and print the decision-log line.
- [X] T018 [US1] In `src/sentinel/cli.py`:
  - **`fetch-prices --source yahoo|tiingo [--limit N] [--retry-failures]`**, replacing the stub; progress every 250 items; exit 6 outside the window for Tiingo;
  - **`prices`**: `_step_prices` registered in `STEPS`;
  - **`tiingo-status`**: exit 1 if any Tiingo data lies outside the register;
  - **`tiingo-delete [--yes]`**: a dry run without `--yes`, exit 2.
- [X] T019 [US1] In `src/sentinel/warehouse.py`:
  - add W12 (revised), W13 for the price keys, W14 and W15 to `check_invariants`, each skipped when its tables are absent;
  - add the price tables to `PRIMARY_KEYS`.
- [X] T020 [US1] `tests/integration/test_prices_real.py` (`@slow`):
  - a real Yahoo ticker with a reverse split in `stg.price_yahoo` satisfies the as-traded relation and equal dollar volume;
  - SPY's 2024 sessions number 252 and exclude 2024-03-29 and 2024-07-04.
- [X] T021 [US1] **Real run, free part**:
  - run `uv run sentinel fetch-prices --source yahoo --limit 20`, then the full pull, then `cap uv run sentinel prices`;
  - run T020;
  - record in `specs/004-market-data-events/run-notes.md` the tickers stored and failed, rows, chosen series, `audit.price_issue` counts, time and peak memory.
- [ ] T022 [US1] **Real run, paid part** (Thursday 29 October, after the researcher subscribes and sets `ops.tiingo_paid_until`):
  - `uv run sentinel tiingo-status`;
  - `fetch-prices --source tiingo --limit 10`, then the full pull;
  - `cap uv run sentinel prices`;
  - record the resolved, rejected (by reason) and fallback counts, and the register totals, in the run notes.

**Checkpoint**: `core.price_daily` covers Yahoo issuers (and Tiingo issuers after T022). US1 is testable on its own.

---

## Phase 4: User Story 2 — Final events that could really have been traded (P2)

**Goal**: G8, final A/B1/B2 events from 2011-07-01 with G7, floors and a 63-session cooldown, unpriced events counted, the coverage report and the golden set.

**Independent test**: `uv run pytest tests/unit/test_g8.py tests/unit/test_final_events.py tests/unit/test_truncation_events.py tests/unit/test_audit_004.py` on `market()` fixtures. Then T036 on the real warehouse.

### Tests (write first)

- [X] T023 [P] [US2] `tests/unit/test_g8.py`:
  - **Spec US2 acceptance 1**: $200 against a 1.80–2.10 range fails `outside_range`.
  - **Boundaries** are inclusive at `low × 0.9` and `high × 1.1`.
  - **Weekend trade date**: uses the Friday session.
  - **`no_session`**: a trade date before the series starts.
  - **Unpriced issuers**: their lines get no `core.price_check` row and their purchases get `g8_status = skipped_unpriced`.
  - **G6 re-applied**: removing one line drops a $30k purchase below $25k, so it leaves `core.priced_purchase`.
  - **`audit.g8_rate`**: totals by year.
- [X] T024 [P] [US2] `tests/unit/test_final_events.py` (spec US2 acceptance 2–7). The candidate outcome order is cooldown → G7 → priced → floors.
  - **G7**:
    - SIC 6726 in the header → `g7_issuer_type`;
    - no header SIC → `g7_no_sic` under `exclude`;
    - under `current_sic`, the fallback takes `core.issuer.sic`, and an issuer with no current SIC is still excluded;
    - no stored header → `needs_header`.
  - **Price floor**: an as-traded close of $1.95 at T fails `floor_price`, even though the later adjusted close is above $2.
  - **Activity and liquidity floors**: 15 of 20 active sessions fails `floor_activity`. An ADDV20 of $80,000 fails `floor_liquidity`. Missing rows count as zero dollar volume and as inactive.
  - **Cooldown**:
    - two qualifying clusters 40 sessions apart → the second is `cooldown`;
    - a floor-failing candidate does not start a cooldown, so a valid candidate 10 sessions later becomes an event;
    - an unpriced candidate is kept as `unpriced` and starts a cooldown.
  - **Calendar**:
    - T on Good Friday → `t_session` is Thursday and `entry_session` is the next Monday;
    - a T dated on a session → `entry_session` is the next session.
  - **Window flag**: warm-up events (T < 2012-01-01) have `in_labelled_window = false`.
  - **Invariants**: W18–W21 hold on the fixture.
- [X] T025 [P] [US2] `tests/unit/test_truncation_events.py`, synthetic. In each case, `detect(cutoff=T)` must equal the full run for everything dated ≤ T: G8, candidates, outcomes, floor values and events.
  - a reverse split after T;
  - a floor that would pass only with later prices;
  - a cooldown chain crossing T;
  - an XBRL share count filed after T.
- [X] T026 [P] [US2] Golden-sheet part of `tests/unit/test_audit_004.py`:
  - the layout of [contracts/audit-sheets.md](contracts/audit-sheets.md) (one row per member, event columns repeated);
  - seed 20261025;
  - 10 per group, with a shortfall filled from A;
  - existing sheets kept without `--force`;
  - the summary counts events with all three checks `yes`, and exits 1 while verdicts are blank.

### Implementation

- [X] T027 [US2] In `src/sentinel/events/prelim.py`, give `find_events` two new parameters:
  - **`keep`**: a callable from candidates to kept candidates. The default is the existing `_cooldown(…, rules.prelim_cooldown_calendar_days)`. Passing `keep=None` returns all candidates.
  - **`start`**: the earliest T.
  
  Feature 002's tests (`tests/unit/test_prelim_events.py`) must pass unchanged.
- [X] T028 [US2] In `src/sentinel/core/gates.py`, parametrise `build_clean_purchases` with `target` (default `core.clean_purchase`) and an optional `line_filter` SQL. Defaults change nothing (feature 002's tests pass). Use it to build `core.priced_purchase`, adding the `g8_status` column.
- [X] T029 [US2] Implement G8 in `src/sentinel/events/final.py`: `build_price_check(con, params, cutoff=None, issuers=None)`.
  - **`core.price_check`**: an ASOF join of each line passing G1–G6a at a priced issuer onto `core.price_daily`, at the last session ≤ trade date. It passes when `low × (1 − tol) ≤ price ≤ high × (1 + tol)`, with tol = `registered.g8_tolerance`.
  - **`audit.g8_rate`**.
  - **`core.priced_purchase`**: via T028.
- [X] T030 [US2] Implement detection in `src/sentinel/events/final.py`: `detect(con, params, cutoff=None, issuers=None, floors=True)`.
  1. **Candidates**: `find_events(purchases="core.priced_purchase", keep=None, start=rules.final_detection_start)`.
  2. **Inputs**:
     - the signal header SIC from `core.filing_header`;
     - `t_session` and `t_session_no` from `core.session`;
     - floor inputs in SQL over `core.price_daily` rows ≤ `t_session`: `close_t` from the last row; `addv20` = the mean of `dollar_volume` over the 20 sessions, missing = 0; `active_sessions_20`.
  3. **Sequential pass in Python**, per (issuer, group) in date order. Outcomes are listed in [data-model.md](data-model.md). A cooldown is started by `event` and `unpriced` outcomes, and the distance uses `registered.cooldown` sessions.
  4. **Writes**: `evt.event_candidate`, `evt.event`, `evt.event_member` and `audit.event_funnel`. Market-cap columns stay null until US4.
  5. **Coverage**: with `floors=False`, write `audit.price_coverage` for A and B1 events from 2012. `delisting_status` is `listed` (chosen series reaches the data's end), `delisted` (series ends earlier) or `unpriced_issuer`. `covered` means the series' first row ≤ session T−19 and last row ≥ T+1.
- [X] T031 [US2] In `src/sentinel/ingest/sec_headers.py`, add `final_targets(con, paths)`: the signal accessions of `needs_header` candidates without a stored header, failures excluded unless asked. Add `fetch-headers --final` to `src/sentinel/cli.py`.
- [X] T032 [US2] In `src/sentinel/cli.py`:
  - **`detect [--fetch-missing-headers]`**, replacing the stub. It exits 3 with the count and the hint `sentinel fetch-headers --final` when headers are missing. With the flag it fetches them and reruns, at most 3 rounds. It prints the G8 rate, outcomes by group and coverage. It runs the floors-off pass after the main pass.
  - **`coverage`**, which writes `specs/004-market-data-events/coverage.md`:
    - SC-001: coverage by year × delisting status, against the 90% target;
    - SC-002: the G8 rate, against 95%;
    - unpriced events by year × group;
    - placeholders for the US3 and US4 sections.
  - `_step_detect` in `STEPS`.
- [X] T033 [US2] Implement `make_golden_sheet` and `summarize_golden` in `src/sentinel/core/audit.py`, and add `sentinel audit golden [--force]` and `audit golden-summary`, writing to `Paths.audits_004`.
- [X] T034 [US2] In `src/sentinel/warehouse.py`, add W16–W21 to `check_invariants`, and add `evt.event`, `evt.event_candidate` and `core.price_check` to `PRIMARY_KEYS`.
- [X] T035 [US2] `tests/integration/test_truncation_events_real.py` (`@slow`, W25): 20 random (issuer, T) pairs with seed 20261023. For each pair, a scratch DuckDB (`memory_limit = warehouse.MEMORY_LIMIT`, `threads = 4`, each result fetched immediately) runs `detect(cutoff=T, issuers=[issuer])` and compares with the full warehouse.
- [X] T036 [US2] **Real run, free part**:
  - `uv run sentinel fetch-headers --final`, then `cap uv run sentinel detect`;
  - `uv run sentinel coverage`;
  - `cap uv run pytest -m slow tests/integration/test_truncation_events_real.py`.
  
  Record outcomes by group and the G8 rate in the run notes. Tiingo issuers stay unpriced until T037.
- [ ] T037 [US2] **Real run after Tiingo** (29–30 October):
  - set `rules.g7_no_sic` from the researcher's D45 result: `current_sic` if 3 or more of the 30 are operating companies;
  - `cap uv run sentinel detect`, then `sentinel coverage`;
  - check SC-001 (≥ 90%) and SC-002 (≥ 95%);
  - `uv run sentinel audit golden` → **researcher**.
- [ ] T038 [US2] **Researcher**: fill in `audits/golden_set.csv` (about 1 hour). Then run `uv run sentinel audit golden-summary`, and fix or explain every difference (SC-003). Record the result in the run notes.

**Checkpoint**: final events exist, with coverage and G8 reported. The MVP of this feature is US1 + US2.

---

## Phase 5: User Story 3 — How each early-ending price series ended (P3)

**Goal**: the SEC filing histories and current profiles of universe issuers, and a delisting class, venue, return and bounds for every early-ending series.

**Independent test**: `uv run pytest tests/unit/test_sec_company.py -k submissions tests/unit/test_delistings.py tests/unit/test_audit_004.py -k delisting`.

### Tests (write first)

- [X] T039 [P] [US3] Submissions part of `tests/unit/test_sec_company.py`, using `submissions_zip`:
  - `recent` arrays and every `files` page are merged;
  - forms 3, 4, 5 and 144 and their amendments are dropped;
  - subject-company forms (25-NSE, SC 14D9, SC TO-T, 425) are kept;
  - `core.issuer` holds the current SIC, exchanges and tickers;
  - only universe issuers are read.
- [X] T040 [P] [US3] `tests/unit/test_delistings.py` (spec US3 acceptance 1–4):
  - **Classes**:
    - a merger proxy 5 months before the last trade → `acquired`, 0%;
    - a Nasdaq company with Form 25 and no merger filing → `performance`, −55%; an NYSE one → −30%;
    - no evidence → `unknown`, with the performance return and bounds −1.0 and 0.0;
    - a 10-Q filed 120 days after the last price → `remap`, with `remap_status = not_found` and the unknown return when no other ticker resolves.
  - **Evidence windows**:
    - merger forms within 12 months before the last trade, inclusive;
    - performance forms from 12 months before to 12 months after;
    - prefix matching, so `DEFM14A/A` counts;
    - merger evidence wins over a 25-NSE.
  - **Venue**: an OTC final ticker with an earlier NASDAQ ticker → `nasdaq`; only OTC → `other`, at −55%.
  - **Scope**:
    - a series ending 3 sessions before the data's end is not classified, because the gap rule is 5;
    - unpriced issuers are never classified.
  - **W23** holds.
- [X] T041 [P] [US3] Delisting-sheet part of `tests/unit/test_audit_004.py`:
  - the contract's columns (no prices);
  - seed 20261024;
  - 10 per class, with a shortfall filled from the other classes;
  - `--force`;
  - the summary gives agreement per class and overall.

### Implementation

- [X] T042 [US3] Implement `src/sentinel/ingest/sec_company.py`:
  - **`fetch(paths, params, client, limiter, policy, refresh=False)`** streams `ops.sec_companyfacts_url` and `ops.sec_submissions_url` to `data/raw/sec/company/{companyfacts,submissions}.zip`, using `sentinel.ingest.http.stream_to_file` and the SEC User-Agent. It writes manifest lines with `source = sec_company`, and skips files already in the manifest unless `refresh`.
  - **Readers**: `iter_submissions(zip_path, ciks)` (the recent arrays plus pages, as one record per CIK) and `read_companyfacts(zip_path, cik)`. Members are opened one at a time.
- [X] T043 [US3] Implement `src/sentinel/core/company.py`: `build_profiles(con, paths, params, issuers=None)`, which writes `core.issuer` and `core.company_filing` for the universe (issuers with a preliminary event from `rules.final_detection_start`), in chunked inserts of 500 issuers.
- [X] T044 [US3] Implement `src/sentinel/core/delistings.py`: `build(con, params) -> DelistingReport`.
  - Classes per research R11, in the order remap → acquired → performance → unknown.
  - Venue from `core.tiingo_listing`, or for Yahoo issuers from the latest SEC ticker snapshot.
  - Returns from `registered.delisting_returns`.
  - Re-map: during the paid month, the issuer's other SEC tickers are tried against `core.tiingo_listing`; the result goes in `remap_status`.
- [X] T045 [US3] Implement `make_delisting_sheet` and `summarize_delistings` in `src/sentinel/core/audit.py`.

  In `src/sentinel/cli.py`, add:
  - `fetch-company` (exit 5 on 403);
  - `company-facts` (profiles now; facts are added in US4), replacing the `shares-out` stub;
  - `delistings`;
  - `audit delistings [--force]` and `audit delistings-summary`;
  - `_step_company` and `_step_delistings` in `STEPS`.
  
  `coverage.md` gains the delisting section: classes × venue counts.
- [X] T046 [US3] In `src/sentinel/warehouse.py`, add W23 and the `core.delisting` and `core.company_filing` keys.
- [ ] T047 [US3] **Real run**:
  - `uv run sentinel fetch-company` (about 3 GB);
  - `cap uv run sentinel company-facts`;
  - after T022, `cap uv run sentinel delistings`;
  - `uv run sentinel audit delistings` → **researcher** (about 45 min);
  - then `audit delistings-summary`, with a target of ≥ 90% (SC-004).
  
  Record the class counts and agreement in the run notes.

**Checkpoint**: every early-ending series has a class, a return and bounds.

---

## Phase 6: User Story 4 — Company size and financials as first reported (P4)

**Goal**: first-filed XBRL values for shares outstanding and the five F26–F29 items, and market capitalisation at T on every priced event.

**Independent test**: `uv run pytest tests/unit/test_sec_company.py -k facts tests/unit/test_final_events.py -k market_cap`.

### Tests (write first)

- [X] T048 [P] [US4] Facts part of `tests/unit/test_sec_company.py` (spec US4 acceptance 1 and 3):
  - **Restatements**: a value restated in a later filing keeps the first-filed value and date.
  - **Ties**: on equal `filed`, the smallest accession wins.
  - **Fallback tags**:
    - `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` is used only for periods with no `StockholdersEquity`, with `tag_used = fallback`;
    - likewise `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` and `ProfitLoss`;
    - liabilities have no fallback tag, because assets − equity is computed at use.
  - **Shares** come only from `dei:EntityCommonStockSharesOutstanding`.
  - **Durations** keep `period_start`.
- [X] T049 [P] [US4] Market-cap cases in `tests/unit/test_final_events.py` (spec US4 acceptance 2, W22):
  - market cap = `close_t` × the shares with the latest `filed ≤ T`, then the latest period end;
  - shares filed the day after T are ignored;
  - no shares filed on or before T → null.

### Implementation

- [X] T050 [US4] Add `build_facts(con, paths, params, issuers=None, cutoff=None)` to `src/sentinel/core/company.py`, writing `core.xbrl_fact` by reading each universe issuer's companyfacts member. Key: "(`issuer_cik`, `concept`, `unit`, `period_start`, `period_end`)"; first-filed rule "the earliest `filed`, then the smallest accession". `sentinel company-facts` now builds profiles and facts.
- [X] T051 [US4] In `src/sentinel/events/final.py`, fill `shares_outstanding`, `shares_filed` and `market_cap` on `evt.event` when `core.xbrl_fact` exists, inside the same cutoff scope (facts filed ≤ cutoff).
- [X] T052 [US4] Implement `audit market-caps` in `src/sentinel/core/audit.py` and `src/sentinel/cli.py`:
  - choose 10 single-class, currently listed event companies with recent share counts, and set them in `ops.market_cap_examples`;
  - on the first run, fetch yfinance `Ticker(t).fast_info["market_cap"]` once per ticker into `data/raw/yahoo/market_cap/{ticker}.json`, with manifest lines;
  - compare with this pipeline's value at the latest session;
  - write `audits/market_caps.csv` per the contract, rounded to $1 million, with no prices.
- [X] T053 [US4] Add W22 to `src/sentinel/warehouse.py`. `coverage.md` gains XBRL coverage per item: the share of events from 2012 with a value first filed on or before T, by year.
- [ ] T054 [US4] **Real run**:
  - `cap uv run sentinel company-facts`, then `cap uv run sentinel detect`;
  - `uv run sentinel audit market-caps`, with a target of 10 of 10 within 5%, or each miss explained (SC-005);
  - `sentinel coverage`.
  
  Record the results in the run notes.

**Checkpoint**: market capitalisation at T exists wherever the cover-page share count does.

---

## Phase 7: User Story 5 — The cost of trading each event (P5)

**Goal**: the tick-size pilot intervals and, for every priced event, the spread, volatility, impact and round-trip cost, plus `costs.md`.

**Independent test**: `uv run pytest tests/unit/test_finra.py tests/unit/test_costs.py`.

### Tests (write first)

- [X] T055 [P] [US5] `tests/unit/test_finra.py`, using a small committed excerpt of FINRA's public change file in `tests/fixtures/finra_tick_pilot_excerpt.txt`, with CRLF line endings as served:
  - the C→G1 change on 2016-10-03 opens a `G1` interval;
  - the G1→C change on 2018-10-01 closes it;
  - control-only tickers produce no rows;
  - deletions close intervals;
  - the `END_FILE` trailer is ignored.
- [X] T056 [P] [US5] `tests/unit/test_costs.py`:
  - **Abdi–Ranaldo recovery**: on a simulated path with a known 2% spread, the estimate recovers it within 25% over 250 sessions.
  - **Negative two-day estimates** are averaged as they are, before `max(·, 0)`.
  - **Tick floor**: $0.01 ÷ `close_t`, or $0.05 for a pilot stock-day.
  - **Volatility**: fewer than 40 returns → null cost, flagged.
  - **The §6.8 illustration**: $2, 1% spread, 4% volatility, ADDV $100k → 3.5% ± 0.1%; with ADDV $1M → 1.8% ± 0.1%.
  - **Corwin–Schultz** is computed.
  - **W24** holds.

### Implementation

- [X] T057 [US5] Implement `src/sentinel/ingest/finra.py` (fetch `ops.finra_tick_pilot_url` into `data/raw/finra/` with a manifest line, and parse the file), and `build_tick_pilot` in `src/sentinel/core/reference.py`, which writes `core.tick_pilot` with `valid_to` exclusive. Add `fetch-reference` (the FINRA part) and the `reference` step (`_step_reference`) to `src/sentinel/cli.py`.
- [X] T058 [US5] Implement `src/sentinel/events/costs.py`: `build(con, params, cutoff=None, issuers=None)`, which writes `evt.event_cost` for priced events using the formulas in research R14 and the [data-model.md](data-model.md) columns.

  `write_report(con, path)` writes `costs.md`:
  - median and quartiles of spread and cost by as-traded price bucket, for development events (2012–2022);
  - a below-$2 bucket computed on the fly from candidates failing only `floor_price`;
  - a flag on any boundary other than $2 where the median cost changes by more than half.
  
  Add `costs` (`_step_costs`) to `src/sentinel/cli.py`.
- [X] T059 [US5] Add W24 and the `evt.event_cost` key to `src/sentinel/warehouse.py`.
- [X] T060 [US5] **Real run**: `uv run sentinel fetch-reference`, `sentinel reference`, then `cap uv run sentinel costs`. Record the bucket table, any flagged jump and the Corwin–Schultz agreement in the run notes.

**Checkpoint**: every priced event has a cost estimate.

---

## Phase 8: User Story 6 — Reference series for benchmarks and industries (P6)

**Goal**: French factors, industries, SIC definitions and size breakpoints in the warehouse.

**Independent test**: `uv run pytest tests/unit/test_french.py`.

### Tests (write first)

- [X] T061 [P] [US6] `tests/unit/test_french.py`, using small committed excerpts of the public files in `tests/fixtures/french/`:
  - free-text lines are skipped;
  - the 49-industry file's two sections ("Average Value Weighted Returns -- Daily" and "Average Equal Weighted Returns -- Daily") map to `vw` and `ew`;
  - percent → decimal;
  - −99.99 → null;
  - `Siccodes49` ranges parse into (industry_no, industry, sic_from, sic_to);
  - ME breakpoints parse;
  - momentum and short-term reversal merge into `core.ff_factor_daily`.

### Implementation

- [X] T062 [US6] Implement `src/sentinel/ingest/french.py` (fetch `ops.french_files` from `ops.french_base_url` into `data/raw/french/`, with manifest lines, and parse them). Extend `src/sentinel/core/reference.py` to build `core.ff_factor_daily`, `core.ff_industry_daily`, `core.sic_industry` and `core.me_breakpoint`. `fetch-reference` and `reference` now cover French and FINRA. `reference` prints the last date and the header SICs that map to no 49-industry portfolio.
- [X] T063 [US6] **Real run**: `uv run sentinel fetch-reference`, then `sentinel reference`. Record the last date (expected 2026-08-31) and the unmapped SIC list in the run notes.

**Checkpoint**: all six stories are complete.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T064 Extend `sentinel build` in `src/sentinel/cli.py`:
  - after feature 002's steps, run `prices` → `reference` → `company-facts` → `detect` → `delistings` → `costs` → `invariants`;
  - skip, with a note, any step whose raw inputs are absent;
  - never fetch: missing headers are an error.
- [X] T065 [P] Add `tests/guards/test_no_tiingo_data.py`: no file under `tests/` holds the Tiingo CSV header unless it is marked `# synthetic`, and no file name under `tests/` contains `tiingo` except test modules.
- [ ] T066 **Offline rebuild (SC-008, before the paid month ends)**: write `tests/integration/test_rebuild_identical.py` (`@slow`). It rebuilds into a scratch warehouse with the network unavailable and compares every feature-004 table, as sorted sets, with `data/warehouse.duckdb`. Run `time cap unshare -rn uv run sentinel build` (under 30 minutes) and log the result in the run notes.
- [ ] T067 [P] Record the peak memory of every new step (cgroup `memory.peak` of each `systemd-run` unit) in the run notes; all must be under 5 GB (SC-009).
- [ ] T068 [P] Update the docs:
  - `docs/initialplan.md`: the §8.2 data model rows for the new tables; Steps 7–10 status;
  - `README.md`: the new commands;
  - `docs/explore.md`: the new tables to browse;
  - `docs/planning/`: status of epics E2 and E3.
- [ ] T069 Complete `specs/004-market-data-events/run-notes.md`: counts, coverage, G8 rate, audits, timings and any deviations. Tick this file's tasks. Run `uv run pytest`, `uv run ruff check .` and `uv run sentinel build`; all must pass.
- [ ] T070 Commit, merge `004-market-data-events` into `main` and delete the branch (keep `gh-pages`). Push only after the researcher approves. Target: Tuesday 3 November 2026, before `prereg-v1` on 4 November (SC-010).
- [ ] T071 **End of the paid month** (about 28 November, after the research that needs Tiingo data):
  - `uv run sentinel tiingo-status`, then `uv run sentinel tiingo-delete`, then `uv run sentinel tiingo-delete --yes`;
  - record the printed line in `docs/initialplan.md` §12;
  - confirm no copy of `data/` exists elsewhere (SC-007).

---

## Dependencies & Execution Order

- **Setup (T001–T002)**, then **Foundational (T003–T009)**:
  - T003 → T005 → T006;
  - T004, T007 and T008 can run in parallel with T005;
  - T009 needs T005.
- **US1 (T010–T022)**: needs Foundational.
  - T014 and T015 can run in parallel; T016 needs both; T017 needs T016; T018 needs T014–T017.
  - **T022 waits for the researcher's Tiingo subscription (29 October).**
- **US2 (T023–T038)**: its tests use `market()` fixtures, so they need only Foundational.
  - T027 and T028 can run in parallel; T029 needs T028; T030 needs T027 and T029; T031 and T032 need T030.
  - The real runs need US1: T036 needs T021, and T037 needs T022 and the D45 result.
- **US3 (T039–T047)**: tests need only Foundational. T042 → T043 → T044 → T045. The real run of `delistings` needs T022.
- **US4 (T048–T054)**: T050 needs T042 and T043; T051 needs T030.
- **US5 (T055–T060)**: T058 needs T030 (events) and T057 (pilot intervals).
- **US6 (T061–T063)**: independent. It extends T057's `reference` step.
- **Polish (T064–T071)**: T066 must run before the paid month ends; T071 runs at its end.

### Critical path (feature complete by Tuesday 3 November)

T003 → T005 → T016 → **T021 (Yahoo prices)** → T030 → **T036 (events on free data)** → **T022 (Tiingo, 29 Oct)** → **T037 (final events + golden set to the researcher)** → T044 → **T047 (delisting sheet to the researcher)** → T058 → T066 → T069 → T070

### The researcher's involvement

- **By Thursday 29 October**:
  - fill in the D45 sheet from T001 (sets `rules.g7_no_sic`);
  - subscribe to Tiingo Power with auto-renew off, and give the plan's end date for `ops.tiingo_paid_until`.
- **Friday 30 – Saturday 31 October**: the golden set (T038, about 1 hour) and the delisting sheet (T047, about 45 minutes). Review the market-cap sheet (T054).
- **Monday 2 November**: approve the merge and push (T070).
- **About 28 November**: approve the Tiingo deletion (T071).

---

## Parallel Examples

```bash
# Foundational, after T003
Task: "plan Appendix E + D50/D51 (T004)"  Task: "Tiingo guard (T007)"  Task: "test builders (T008)"

# US1 tests together
Task: "test_yahoo.py (T010)"  Task: "test_tiingo.py (T011)"  Task: "test_prices.py (T012)"  Task: "test_tiingo_register.py (T013)"

# US1 fetchers together
Task: "ingest/yahoo.py (T014)"  Task: "ingest/tiingo.py (T015)"

# US2 tests together
Task: "test_g8.py (T023)"  Task: "test_final_events.py (T024)"  Task: "test_truncation_events.py (T025)"  Task: "golden sheet tests (T026)"

# Free-data stories once US1/US2 code exists
Task: "US3 sec_company + delistings (T039–T046)"  Task: "US5 finra + costs (T055–T059)"  Task: "US6 french (T061–T062)"
```

---

## Implementation Strategy

1. **MVP**: Phases 1–4 (US1 + US2) on free data first. These are Yahoo prices, final events at Yahoo-priced issuers, G8 and coverage; Tiingo issuers stay unpriced and are counted.
2. **Before 29 October**: the remaining code (US3–US6) is built and tested on synthetic data, and run on the free sources (SEC bulk, French, FINRA).
3. **29 October**: the Tiingo pull, one `build`, coverage, and the audit sheets to the researcher.
4. **30 October – 2 November**: fixes from the audits, the offline rebuild check, the real-data truncation test, run notes and the merge.

### Notes

- **No returns**: no code in this feature computes a post-event return, label or outcome (constitution III). Prices after T are stored for later features only.
- **Tiingo**: every Tiingo-derived table carries `price_source` and is listed in `TIINGO_DERIVED`. The guard (exit 6) blocks writes outside the paid window. Test fixtures are synthetic.
- **Rules after the tag**: any change to `rules` or `registered` after `prereg-v1` is a logged deviation (feature 002's params-rules contract).
