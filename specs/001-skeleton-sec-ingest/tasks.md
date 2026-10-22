---

description: "Task list for feature 001: project skeleton, SEC insider-data ingest and provisional delisted-candidate list"
---

# Tasks: Project Skeleton, SEC Insider-Data Ingest and Provisional Delisted-Candidate List

**Input**: Design documents from `specs/001-skeleton-sec-ingest/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: included. FR-007 requires an offline test suite, and the constitution requires unit and guard tests before merging to `main`. In each story, write the test tasks first and confirm that they fail.

**Organization**: tasks are grouped by user story. US1 (P1) is the SEC archive, US2 (P2) the provisional candidate list, and US3 (P3) the parameter register, `check` and the guards.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: US1, US2 or US3. Setup, Foundational and Polish tasks carry no story label.
- Paths are relative to the repository root (single project, `src/` layout).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: a buildable `edgar-sentinel` package with locked dependencies.

- [X] T001 Create and switch to git branch `001-skeleton-sec-ingest` from `main` in the repository root (`git switch -c 001-skeleton-sec-ingest`). Commit nothing yet.
- [X] T002 Rewrite `pyproject.toml`:
  - **Project**: `name = "edgar-sentinel"`, `version = "0.1.0"`, a one-line description, `readme = "README.md"`, `requires-python = ">=3.14"`.
  - **Dependencies** (pins from research.md R9): `httpx>=0.28.1,<0.29`, `duckdb>=1.5.6,<2`, `pyarrow>=25.0.1,<26`, `pyyaml>=6.0.3,<7`, `python-dotenv>=1.2.4,<2`, `typer>=0.27.3,<0.28`.
  - **Dev group** (`[dependency-groups] dev`): `pytest>=9.1.1,<10`, `ruff>=0.17.1,<0.18`, `respx>=0.23.1,<0.24`.
  - **Script**: `[project.scripts] sentinel = "sentinel.cli:app"`.
  - **Build**: `[build-system] requires = ["uv_build>=0.11,<0.12"]`, `build-backend = "uv_build"`, and `[tool.uv.build-backend] module-name = "sentinel"`.
  - **Ruff**: `[tool.ruff]` with `line-length = 100` and `target-version = "py314"`; `[tool.ruff.lint] select = ["E","F","I","UP","B","SIM"]`.
  - **Pytest**: `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, `addopts = "-ra"`, `markers = ["network: needs internet; run with --run-network"]`.
- [X] T003 [P] Delete `main.py`. Add `data/` and `*.part` to `.gitignore`, keeping the existing `.env` and Python entries.
- [X] T004 [P] Create the package skeleton:
  - `src/sentinel/__init__.py` with `__version__ = "0.1.0"`;
  - `src/sentinel/ingest/__init__.py`;
  - `src/sentinel/provisional/__init__.py`, whose module docstring says: "Provisional, look-ahead code (uses today's SEC ticker map). Used only to prioritise the delisted-price pull. Never import from production code.";
  - empty folders `tests/unit/`, `tests/guards/`, `tests/network/` and `tests/fixtures/`.
- [X] T005 Run `uv sync` to create `.venv` and `uv.lock`. Confirm that `uv run python -c "import sentinel, duckdb, pyarrow, httpx, typer, yaml, dotenv"` succeeds and that `uv run python -c "import duckdb; print(duckdb.__version__)"` prints a 1.5.x version.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the parameter file, config and secrets, the test harness and the CLI shell. Every story depends on these.

**⚠️ CRITICAL**: no user-story work can begin until this phase is complete.

- [X] T006 Create `config/params.yaml` exactly as structured in contracts/params-schema.md.
  - **`version: 1`.**
  - **`registered`**: one entry for each of the **34** data rows of the Appendix E table in `docs/initialplan.md` (the section headed "Appendix E — Parameter register"). Each entry has a machine-readable `value`, a `unit`, a `sensitivity` list where the row has variants, and a `register` block whose `parameter`, `value` and `sensitivity` strings are copied verbatim from the row's cells.
  - **Keys, in table order**: `insider_data_period`, `labelled_window_start`, `holdout`, `g6_min_value`, `g6_timeliness`, `g8_tolerance`, `cluster_window`, `cluster_min_entities`, `cluster_min_value`, `cooldown`, `price_floor`, `position_size`, `liquidity_floor`, `activity_floor`, `horizons`, `primary_horizon`, `factor_beta_window`, `spread_addv_window`, `volatility_window`, `impact_coefficient`, `delisting_returns`, `merger_lookback`, `selling_lookback`, `repeat_buying_lookback`, `routine_definition`, `f10_shrinkage`, `winsorising`, `training_window_split`, `fold1_min_fit_size`, `portfolio_cutoff`, `calendar_time_min_positions`, `newey_west_lags`, `significance`, `model_grids`.
  - **Required values**: `insider_data_period.value = {start: 2006q1, end: 2026q3}`, `labelled_window_start.value = 2016-01-01`, `g6_min_value.value = 10000`, `g6_timeliness.value = 30`, `cluster_window.value = 14`, `cluster_min_value.value = 100000`.
  - **`ops`**: exactly as in the contract (target 5 and ceiling 10 requests per second, timeouts, retries, the landing-page URL, both folder patterns, the ticker-map URL, the Tiingo list URL, `required_archive_tables`).
  - **`provisional`**: as in the contract, with the regular expressions from research.md R3 (`common_title_regex`, `excluded_title_regex`, `plan_footnote_regex`, `offering_footnote_regex`) and R6 (`ceo_cfo_title_regex`), `tiingo_us_exchanges`, and the full `pilot_reference` (all five `by_start_year` rows, `funnel_2019q1` and `funnel_2023q1`).
- [X] T007 Implement `src/sentinel/config.py`:
  - **Paths**:
    - `repo_root()` returns the nearest parent folder containing `pyproject.toml`;
    - a frozen `Paths` dataclass with `data_raw=data/raw`, `sec_insider=data/raw/sec/insider`, `sec_reference=data/raw/sec/reference`, `manifest=data/raw/manifest.jsonl`, `lock=data/raw/.lock` and `provisional=data/provisional`.
  - **Parameters**: `load_params(path)` returns a dict. It raises `ConfigError` if `registered`, `ops` or `provisional` is missing, if a key appears in more than one section, if `ops.sec_max_requests_per_second > 10`, or if a `provisional` regex fails to compile. It also exposes `params_sha256(path)`.
  - **Secrets**: `load_secrets(env_path)` uses `dotenv_values` and does not export into `os.environ`.
    - `SEC_USER_AGENT` is required. It "must contain an e-mail address" (regex `[^@\s]+@[^@\s]+\.[^@\s]+`); otherwise raise `ConfigError`.
    - Return a warning flag when the value is only an e-mail with no name part.
    - `TIINGO_API` is optional.
  - **Redaction**: `redact(text)` replaces every secret value with `***`. `RedactingFilter(logging.Filter)` applies `redact` to the message and args of each log record.
  - **Errors**: `ConfigError(Exception)`.
- [X] T008 [P] Implement `tests/conftest.py`:
  - an autouse fixture that monkeypatches `socket.socket.connect` and `socket.create_connection` to raise `RuntimeError("network blocked in tests")` unless the test carries the `network` marker;
  - a `pytest_addoption` hook adding `--run-network`, and a `pytest_collection_modifyitems` hook that skips `network` tests without it;
  - fixture `fake_env(tmp_path)` writing a `.env` with `SEC_USER_AGENT="Test User test@example.com"` and `TIINGO_API=tiingo-secret-123`;
  - fixture `tmp_data(tmp_path)` returning a `Paths` rooted in `tmp_path`;
  - fixture `params` loading the real `config/params.yaml`.
- [X] T009 Implement the CLI shell in `src/sentinel/cli.py`:
  - **App**: `app = typer.Typer(name="sentinel", no_args_is_help=True)`. Exit-code constants in one place: `OK=0`, `FAILED=1`, `USAGE=2`, `CONFIG=3`, `NOT_IMPLEMENTED=4`, `SEC_FORBIDDEN=5`.
  - **Help panels**: `Phase 0 — Set-up`, `Phase 1 — Insider data`, `Phase 2 — Prices, labels, features`, `Phase 3 — Analysis`, `Phase 4 — Holdout and delivery`.
  - **Stubs**: register every stub command in the contracts/cli.md table (`stage`, `entities`, `gates`, `detect-prelim`, `symbols`, `fetch-prices`, `fetch-reference`, `detect`, `delistings`, `shares-out`, `costs`, `prereg-status`, `labels`, `features`, `serve`, `event-study`, `ml-dataset`, `baselines`, `tournament`, `explain`, `holdout`, `score-live`, `robustness`, `report`).
    - Help text is `[Step N] <description>`, with the description taken from the plan §9.2 step table.
    - Each stub prints `not yet implemented — plan Step N` to stderr and exits 4.
  - **Placeholders**: temporary stubs for `check`, `fetch-sec`, `verify-sec`, `fetch-sec-tickers` and `candidates-provisional`, replaced in later tasks.
  - **Logging**: an app callback configures logging at INFO, with `RedactingFilter` on the root handler.

**Checkpoint**: `uv run sentinel --help` lists every step grouped by phase, and `uv run pytest` runs (with no tests yet).

---

## Phase 3: User Story 1 — Fetch the complete SEC insider archive (Priority: P1) 🎯 MVP

**Goal**: all 83 quarterly archives stored immutably in `data/raw/sec/insider/` with a SHA-256 manifest. Downloads are resumable and stay within SEC fair-access rules.

**Independent Test**: on an empty `data/raw/`, `uv run sentinel fetch-sec` followed by `uv run sentinel verify-sec` reports `ok=83`. A second `fetch-sec` fetches nothing. Interrupting a fresh run and rerunning it fetches only the missing quarters.

### Tests for User Story 1 (write first; they must fail)

- [X] T010 [P] [US1] Write `tests/unit/test_http.py`:
  - **Rate limit**: `RateLimiter` with an injected fake clock never allows more than the ceiling in any 1-second window and averages the target rate (5 per second).
  - **Retries** (respx):
    - a 429 with `Retry-After: 1` followed by 200 succeeds on attempt 2 after sleeping at least 1 s;
    - five 503s raise `RetryExhausted`;
    - `httpx.ReadTimeout` followed by 200 succeeds.
  - **Forbidden**: a 403 raises `SecForbidden` after exactly 1 call.
  - **User-Agent**: every request carries `User-Agent` equal to the configured contact.
  - **Streaming**: `stream_to_file` leaves no `.part` file when the stream raises mid-way.
- [X] T011 [P] [US1] Write `tests/unit/test_manifest.py`:
  - **Append**: writes one JSON line with exactly the fields `path, source, key, role, url, fetched_at, bytes, sha256, http_last_modified, http_etag, tool`.
  - **Duplicates**: a second `original` for the same (`source`, `key`), or a duplicate `path`, is rejected.
  - **Verify**: classifies tmp files as `ok`, `mismatch`, `missing` and `unrecorded`, and ignores `*.part` and `.lock`.
  - **Lock**: a second `FetchLock` raises `FetchLocked("another fetch is running")`.
  - **No secrets**: the manifest text never contains the User-Agent or `tiingo-secret-123`.
- [X] T012 [P] [US1] Write `tests/unit/test_sec_bulk.py`, with fixtures `tests/fixtures/sec_landing.html` (a minimal page linking 2019q1 under `/files/structureddata/...` and 2026q3 under `/files/datastandardsinnovation/...`) and a helper that builds a synthetic `{key}_form345.zip` containing `SUBMISSION.tsv`, `REPORTINGOWNER.tsv`, `NONDERIV_TRANS.tsv` and `FOOTNOTES.tsv`. It should cover:
  - **Quarters and URLs**:
    - `quarters_in_range("2006q1","2026q3")` gives 83 keys, the first `2006q1` and the last `2026q3`;
    - discovery maps both folder layouts;
    - a quarter missing from the page falls back to the `ops.sec_folder_patterns` HEAD checks.
  - **Storing**: a successful fetch leaves the final file in mode `0o444` with one manifest line and no `.part`.
  - **Bad archives**: a corrupt zip, or a zip without `FOOTNOTES.tsv`, marks the quarter `failed` and leaves no final file and no manifest line.
  - **Resume**: an exception mid-stream leaves no final file, and the next run removes the stale `.part` and fetches the quarter.
  - **Skip**: a second run makes no HTTP call for a stored quarter whose SHA-256 matches.
  - **Altered file**: a stored file that was changed is reported `failed (stored file differs from manifest)` and is not overwritten.
  - **Isolation**: one failing quarter does not stop the others.
  - **403**: aborts the run.
  - **Refetch**: `refetch="2019q1"` writes `2019q1_form345__refetch_<UTC>.zip` with role `refetch` and leaves the original untouched.
- [X] T013 [P] [US1] Write `tests/network/test_sec_live.py` (marked `network`): one HEAD request for the 2006q1 archive URL, using the real `.env` contact, returns 200 with `Content-Length` > 1,000,000.

### Implementation for User Story 1

- [X] T014 [US1] Implement `src/sentinel/ingest/http.py`:
  - **`RateLimiter(target_rps, max_rps, clock=time.monotonic, sleep=time.sleep)`**: thread-safe, spaces requests at `1/target_rps`, and asserts `max_rps <= 10`.
  - **`make_client(user_agent, timeout)`**: returns an `httpx.Client` with headers `User-Agent` and `Accept-Encoding: gzip, deflate`, with `follow_redirects=True`.
  - **`request_with_retry(client, method, url, limiter, max_attempts, backoff_base, backoff_max)`**:
    - retries HTTP 429, 5xx, `httpx.TimeoutException` and `httpx.TransportError` with exponential backoff and full jitter, honouring `Retry-After`;
    - raises `SecForbidden` on 403 without retrying, and `RetryExhausted` after the last attempt.
  - **`stream_to_file(client, url, final_path, limiter, ...)`**:
    - streams to `final_path + ".part"` in the same folder, computing SHA-256 and the byte count, then flushes and `os.fsync`s;
    - returns `(bytes, sha256, final_url, last_modified, etag)`, and deletes the `.part` file on any exception.
  - **Logging**: each request is logged at DEBUG with a monotonic timestamp, for the rate check.
- [X] T015 [P] [US1] Implement `src/sentinel/ingest/manifest.py`:
  - **`ManifestEntry`**: a dataclass with the fields in contracts/raw-manifest.md.
  - **`append(manifest_path, entry)`**: one `write` plus `flush` plus `os.fsync`. It enforces "each (`source`, `key`) has exactly one `original` line" and unique `path`.
  - **Readers**: `read_all()` and `find_original(source, key)`.
  - **`verify(paths, prefix="sec/")`**: returns `ok`, `mismatch`, `missing` and `unrecorded` lists. A file under `data/raw/sec/` with no line is `unrecorded`, excluding `*.part` and `.lock`.
  - **`sha256_file(path)`**: hashes in 1 MiB chunks.
  - **`FetchLock`**: a context manager using a non-blocking `fcntl.flock` on `data/raw/.lock`. It raises `FetchLocked("another fetch is running")`.
- [X] T016 [US1] Implement `src/sentinel/ingest/sec_bulk.py`:
  - **`quarters_in_range(start, end)`**: driven by `registered.insider_data_period.value`.
  - **`discover_urls(client, limiter, keys)`**: one GET of `ops.sec_landing_page`. It parses `href="…/{key}_form345.zip"` links into absolute `https://www.sec.gov` URLs. For any missing key, it HEADs each `ops.sec_folder_patterns` URL in order, and the first 200 wins.
  - **`validate_archive(path, required)`**: the zip opens, `testzip()` returns `None`, and every `<TABLE>.tsv` is present.
  - **`fetch_quarters(keys=None, refetch=None, dry_run=False)`** implements the state machine in data-model.md §2:
    1. Remove stale `*.part` files.
    2. Skip a stored quarter whose `sha256_file` equals the manifest.
    3. Report a mismatch as `failed (stored file differs from manifest)`, never overwriting it.
    4. Otherwise `stream_to_file`, then `validate_archive`, then `os.replace` to the final name, then `chmod 0o444`, then append a `ManifestEntry` with `source="sec_insider_bulk"`, `role="original"` (or `"refetch"`, with the file name suffix `__refetch_<YYYYMMDDTHHMMSSZ>`) and `tool` set to `sentinel <version>+<git short hash>`.
    5. Return a per-quarter result list and a summary (stored, skipped, failed, bytes). `SecForbidden` propagates.
- [X] T017 [US1] Wire `fetch-sec` (options `--quarters`, `--refetch`, `--dry-run`) and `verify-sec` into `src/sentinel/cli.py`, per contracts/cli.md:
  - **Startup**: load secrets (`ConfigError` → exit 3) and hold `FetchLock` (locked → exit 1).
  - **Progress**: print `stored`, `skipped (verified)` or `failed (<reason>)` per quarter, then the summary line.
  - **Exit codes**: 0 if every quarter is stored, 1 if any failed, 5 on `SecForbidden`, with a message to check `SEC_USER_AGENT`.
  - **`verify-sec`**: offline. It prints counts and non-`ok` lines, and exits 0 only if all 83 quarters are `ok` and nothing is `unrecorded`.
- [X] T018 [US1] Run the real download:
  1. `uv run sentinel fetch-sec --dry-run` shows 83 URLs.
  2. `time uv run sentinel fetch-sec` stores 83 quarters in under 1 hour (SC-004).
  3. `uv run sentinel verify-sec` reports `ok=83`, mismatch=0, missing=0, unrecorded=0 (SC-002).
  4. `time uv run sentinel fetch-sec` again fetches 0 files in under 1 minute (SC-003).

  Record the timings, total bytes and the maximum requests per second seen in the DEBUG log in `specs/001-skeleton-sec-ingest/run-notes.md`.

**Checkpoint**: the SEC archive is complete and verified. US2 can now use real data.

---

## Phase 4: User Story 2 — Produce the provisional delisted-candidate list (Priority: P2)

**Goal**: a ranked, clearly provisional list of likely-delisted companies with A/B1 events from 2006 onward, plus a summary set against the pilot (plan §5.2, A.1, A.3).

**Independent Test**: with the archive present, `uv run sentinel fetch-sec-tickers && uv run sentinel candidates-provisional` writes the files in contracts/provisional-outputs.md. The funnel for 2019 Q1 and 2023 Q1 is within 1% of A.1, every §5.2 row is within ±15%, and two `--no-tiingo` runs give identical CSV hashes.

### Tests for User Story 2 (write first; they must fail)

- [X] T019 [P] [US2] Write `tests/unit/test_sec_tables.py`:
  - a synthetic zip table whose fields contain literal `"` characters keeps its exact row count and values;
  - every column comes back as `pa.string()`;
  - requesting a column absent from the file (`AFF10B5ONE` in a pre-2023 `SUBMISSION.tsv`) returns it as an all-null string column;
  - column projection returns only the requested columns.
- [X] T020 [P] [US2] Write `tests/unit/test_provisional_gates.py`, with synthetic rows loaded into an in-memory DuckDB:
  - **Form and code**: `4/A` is excluded; code P with `acq_disp='D'` is excluded.
  - **Security title**: `Series A Preferred Stock` is excluded; `Class A Common Stock` is kept.
  - **Checkbox**: `aff10b5one` of `1` or `true` excludes every line of that filing; blank or absent does not.
  - **Footnotes**: a plan footnote cited only by *another* line in the same filing does not exclude this line; an offering footnote cited by this line excludes it.
  - **Timeliness**: a trade 31 days before filing is excluded and 30 days is kept; a negative lag is excluded.
  - **Price**: 1.99 is excluded and 2.00 kept.
  - **Filing total**: $9,999 is dropped and $10,000 kept.
  - **Funnel**: for every quarter and gate, `rows_in = rows_out + rows_removed`, and each gate's `rows_in` equals the previous gate's `rows_out`.
- [X] T021 [P] [US2] Write `tests/unit/test_provisional_events.py`:
  - **Window**: two filings by different owners 13 days apart totalling ≥ $100,000 give one A event on the later date. At 14 days apart (outside [T − 13, T]) there is none.
  - **Buyers**: one joint filing with two owners is one buyer, so no A event. Filings with owners {X, Y} and {Y} in one window are one buyer.
  - **B1**: a CEO buying alone for $100,000 gives B1. The same purchase with a second buyer in the window and a total ≥ $100,000 gives A, not B1.
  - **Cooldown**: a qualifying date 90 days after an event is suppressed, and 91 days after is allowed. Cooldowns are separate per group. An event on 2015-12-01 suppresses one on 2016-01-15 (FR-018).
  - **Flag**: `in_labelled_window` is true from 2016-01-01.
- [X] T022 [P] [US2] Write `tests/unit/test_tiingo_match.py`, using in-memory rows only:
  - SEC `BRK.B` matches Tiingo `BRK-B`;
  - a reused ticker with two Tiingo rows matches the one overlapping the event span (`matched`);
  - a ticker found only outside the span gives `ticker_only`; an absent ticker gives `unmatched`;
  - rows that are not on a US exchange, not `Stock` or not `USD` are ignored;
  - a disabled check gives `not_checked`;
  - the matcher takes bytes and returns flags, and writes nothing to `tmp_path` or the working folder.
- [X] T023 [P] [US2] Write `tests/unit/test_candidates.py`:
  - **Ranking**: "by tier ascending, last_signal_date descending, issuer_cik ascending. Dense, starting at 1".
  - **Labelling**: every output file name contains `PROVISIONAL`, and every tabular file's first column is `status` with value `PROVISIONAL`.
  - **Determinism**: two `--no-tiingo` runs on the same fixture give byte-identical CSVs.
  - **Delisted test**: likely delisted means the CIK is absent from the snapshot, even when another CIK now uses the ticker.
  - **Tickers**: `last_ticker` comes from the latest filing of any form, with ties broken by the higher accession number.
  - **Summary**: a §5.2 gap over 15%, or a funnel gap over 1%, is marked `CHECK`.

### Implementation for User Story 2

- [X] T024 [P] [US2] Implement `src/sentinel/ingest/sec_reference.py`:
  - **`fetch_company_tickers(client, limiter, paths)`**: downloads `ops.sec_company_tickers_url` atomically (`.part`, then rename, then `0o444`) to `data/raw/sec/reference/company_tickers_exchange_YYYYMMDD.json`, with a manifest line `source="sec_company_tickers"`, `key=YYYYMMDD`, `role="original"`. It skips if today's snapshot exists.
  - **`latest_snapshot(paths)`**.
  - **`load_snapshot(path)`**: parses `{"fields": ["cik","name","ticker","exchange"], "data": [...]}` into a map from CIK to (tickers, exchanges).
- [X] T025 [US2] Wire `fetch-sec-tickers` into `src/sentinel/cli.py`, with the same exit codes as `fetch-sec`.
- [X] T026 [P] [US2] Implement `src/sentinel/ingest/sec_tables.py`: `read_table(zip_path, table, columns=None) -> pyarrow.Table`.
  - Reads the header line first, then streams `<TABLE>.tsv` from the zip through `pyarrow.csv.read_csv`, with `ParseOptions(delimiter="\t", quote_char=False, double_quote=False, escape_char=False)`, strict UTF-8, and every column as `pa.string()` via `ConvertOptions(column_types=...)`.
  - Projects to `columns` when given, adding any requested column missing from the file as an all-null string column.
- [X] T027 [US2] Implement `src/sentinel/provisional/load.py`: build the scratch database `data/provisional/provisional_PROVISIONAL.duckdb` from the 83 manifest `original` archives, in quarter order.
  - **`p_submission`** (every row): `accession`, `filing_date` (parsed from `DD-MON-YYYY`), `document_type`, `issuer_cik`, `issuer_name`, `symbol_raw`, `quarter`, and `aff10b5one` normalised as `1`/`true` → true, `0`/`false` → false, blank or absent → null.
  - **`p_owner`**: `accession`, `owner_cik`, `relationship`, `title`, `is_officer` (relationship contains `Officer`), `is_director` (contains `Director`), and `is_ceo_cfo` (`is_officer` and the title matches `provisional.ceo_cfo_title_regex`, case-insensitive).
  - **`p_purchase_line`** (`TRANS_CODE='P'` only): `accession`, `line_sk`, `security_title`, `trans_date`, `acq_disp`, `shares` and `price` as DOUBLE (non-numeric → null), and `fn_ids`, a list built from every `*_FN` column split on `,` and trimmed.
  - **`p_footnote`**: only the accessions present in `p_purchase_line`.
  - **Deduplication**: keep the first occurrence in quarter order, keyed by `accession` (or `accession`, `line_sk` and `accession`, `footnote_id`), and record duplicate counts.
  - **Caching**: skip the rebuild when the stored input fingerprint (the list of manifest SHA-256s plus `params_sha256`) is unchanged, unless `rebuild=True`.
- [X] T028 [US2] Implement `src/sentinel/provisional/gates.py`:
  - **Gate flags**: SQL computing the per-line flags in the order of data-model.md §6 (`g_purchase`, `g_original_form4`, `g_common`, `g_no_checkbox`, `g_no_plan_fn`, `g_no_offering_fn`, `g_timely`, `g_price`). It uses the `provisional.*` regexes with `regexp_matches(..., 'i')`, matches footnotes only through the line's own `fn_ids`, and takes thresholds from `registered.g6_timeliness.value` and `provisional.price_standin_floor`.
  - **`clean_filings()`**: per data-model.md §7 — `accession`, `issuer_cik`, `filing_date`, the `owner_ciks` set, `has_ceo_cfo`, and `value_usd`, the sum of shares × price over passing lines, which "must be ≥ `g6_min_value` ($10,000)".
  - **`funnel()`**: one row per quarter × gate with `rows_in`, `rows_out`, `rows_removed`.
- [X] T029 [US2] Implement `src/sentinel/provisional/events.py`:
  - **Window**: per issuer, iterate the distinct clean-filing dates T in order. The window is [T − (`cluster_window` − 1) days, T].
  - **Buyers**: merge the window's filings into buyers by `owner_ciks` overlap (union-find).
  - **A**: buyers ≥ `provisional.min_buyers_cluster` and total ≥ `registered.cluster_min_value.value`.
  - **B1**: exactly one buyer, `has_ceo_cfo` on at least one of its filings, and total ≥ `cluster_min_value`.
  - **Cooldown**: `provisional.cooldown_calendar_days` per issuer and per group, started only by events.
  - **Output**: `issuer_cik`, `group`, `signal_date`, `n_buyers`, `total_value_usd`, `member_accessions`, and `in_labelled_window` (`signal_date ≥ registered.labelled_window_start.value`). Process every year from 2006.
- [X] T030 [P] [US2] Implement `src/sentinel/provisional/tiingo_list.py`:
  - **`fetch_list(client)`**: downloads `ops.tiingo_supported_tickers_url` **into memory only**, with no API key and nothing written to disk. It returns the rows plus only the `Last-Modified` header and the SHA-256 of the bytes.
  - **Filter**: `assetType == "Stock"`, `priceCurrency == "USD"`, and `exchange` in `provisional.tiingo_us_exchanges`.
  - **`normalise(ticker)`**: upper case, trimmed, `.` and `/` replaced by `-`. `NONE`, `N/A` and blank map to none.
  - **`match(tickers, span_start, span_end)`**: returns `matched`, `ticker_only` or `unmatched`, plus the matched SEC ticker (research.md R5).
- [X] T031 [US2] Implement `src/sentinel/provisional/candidates.py`.
  - **Candidates**: per data-model.md §10 and contracts/provisional-outputs.md. Likely delisted means the CIK is absent from the ticker snapshot. Tier 1 if any A event. Columns: `rank`, `last_ticker`, `all_tickers` (joined with `|`, sorted), `n_events_a`, `n_events_b1`, `n_events_labelled`, `first_signal_date`, `last_signal_date`, `tiingo_match`, `tiingo_matched_ticker`.
  - **Files**, all in `data/provisional/` and each with first column `status=PROVISIONAL`: `delisted_candidates_PROVISIONAL.csv`, `events_PROVISIONAL.parquet` and `funnel_PROVISIONAL.csv`.
  - **`summary_PROVISIONAL.md`**, with the contract's six sections:
    - the §5.2 table for start years 2006, 2009, 2011, 2014 and 2016 against `provisional.pilot_reference.by_start_year`, marking `CHECK` above 15%;
    - per-year A and B1 counts against A.3;
    - the 2019 Q1 and 2023 Q1 funnels against `funnel_2019q1` and `funnel_2023q1`, marking `CHECK` above 1%;
    - the count of companies now on OTC or with no exchange;
    - data notes.
  - **`run_PROVISIONAL.json`**: per data-model.md §12.
  - **Sorting**: deterministic everywhere.
- [X] T032 [US2] Wire `candidates-provisional` (options `--tickers-snapshot`, `--no-tiingo`, `--rebuild-scratch`) into `src/sentinel/cli.py`. It requires all 83 quarters stored with matching hashes and a ticker snapshot; otherwise it exits 1 naming what is missing. It prints the §5.2 comparison table to the console.
- [X] T033 [US2] Run it for real:
  1. `uv run sentinel fetch-sec-tickers`, then `uv run sentinel candidates-provisional`.
  2. Read `data/provisional/summary_PROVISIONAL.md` and confirm SC-005 and SC-006. Investigate every `CHECK` mark and write the explanation in `specs/001-skeleton-sec-ingest/run-notes.md`; adjust the `provisional` regexes only with a recorded reason.
  3. Run twice with `--no-tiingo` and confirm identical `sha256sum` of the CSV (SC-007).
  4. Confirm that `find data -iname '*tiingo*'` finds nothing.

**Checkpoint**: the candidate list is ready (SC-008, target 27 Oct 2026). It is the input to the price-pull feature.

---

## Phase 5: User Story 3 — One parameter file and a runnable project foundation (Priority: P3)

**Goal**: the parameter file is proven to match Appendix E, `sentinel check` works, and the guards stop look-ahead code and secrets from leaking.

**Independent Test**: on a fresh clone, `uv sync && uv run sentinel --help && uv run sentinel check && uv run pytest` passes offline, and `uv run sentinel stage` exits 4.

### Tests for User Story 3 (write first; they must fail)

- [X] T034 [P] [US3] Write `tests/unit/test_params_register.py`, implementing contracts/params-schema.md rules 1–6.
  - **Parsing**: parse the Appendix E table in `docs/initialplan.md`: rows after the header and the `|---|` separator, up to the first blank line, giving 34 rows.
  - **Comparison**: compare with `config/params.yaml` through `sentinel.config.check_register(params, plan_path)`. Every row has exactly one `registered` entry with equal verbatim `parameter`, `value` and `sensitivity` cells (after trimming), there are no extra `registered` entries, and `ops` and `provisional` have no `register` block.
  - **Targeted assertions** (rule 5): exact values for `g6_min_value`, `g6_timeliness`, `cluster_window`, `cluster_min_value` and `labelled_window_start`; 83 quarters in `insider_data_period`; `sec_max_requests_per_second` ≤ 10.
  - **Regexes**: every `provisional` regex compiles.
- [X] T035 [P] [US3] Write `tests/unit/test_config.py`:
  - **Contact**: a missing `SEC_USER_AGENT` raises `ConfigError`; a value without `@` raises `ConfigError`; an e-mail-only value returns the warning flag.
  - **Redaction**: `redact()` masks `tiingo-secret-123`, and `RedactingFilter` masks it in `caplog` records.
  - **Params**: `load_params` rejects a key that appears in two sections.
- [X] T036 [P] [US3] Write `tests/unit/test_cli.py`, using typer's `CliRunner`:
  - `--help` contains every command name in contracts/cli.md and all five panel titles;
  - `stage` exits 4 with `not yet implemented — plan Step 2`;
  - an unknown option exits 2;
  - `check` with `fake_env` and the real params exits 0 and never prints `tiingo-secret-123`.
- [X] T037 [P] [US3] Write `tests/guards/test_no_provisional_imports.py`: an AST scan of every `.py` file under `src/sentinel/`, except `src/sentinel/provisional/` and `src/sentinel/cli.py`. It fails if any file imports `sentinel.provisional` in any form.
- [X] T038 [P] [US3] Write `tests/guards/test_secrets_not_tracked.py`:
  - `.env` is matched by `.gitignore` (`git check-ignore .env` succeeds);
  - `git ls-files .env` is empty;
  - `git check-ignore data/raw/x` succeeds.

### Implementation for User Story 3

- [X] T039 [US3] Add `check_register(params, plan_path) -> list[str]` (a list of problems) to `src/sentinel/config.py`.
- [X] T040 [US3] Implement `check` in `src/sentinel/cli.py`, per contracts/cli.md. It prints one `OK`, `WARN` or `FAIL` line for each of:
  - `.env` present;
  - `SEC_USER_AGENT` valid (`WARN` if it is only an e-mail);
  - `TIINGO_API` set or unset, never printing the value;
  - params load, and `check_register` returns no problems;
  - the `data/` folders exist or can be created;
  - `data/` is git-ignored.

  It exits 0 if there is no `FAIL`, otherwise 3.

**Checkpoint**: all three stories work independently, and the whole suite passes offline.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T041 [P] Append decision-log rows **D39–D41** to the table in §12 of `docs/initialplan.md`:
  - **D39**: Tiingo's free plan forbids storing data (ToS §1.6(a), updated 2026-10-06), so one month of Tiingo Power was bought (decided 2026-10-22). The project finishes within that month. Tiingo data is deleted when the plan ends, and the Step 21 offline rebuild runs before then. Alternatives: the free plan with in-memory processing only; dropping delisted stocks (rejected because of survivorship bias, §5.1).
  - **D40**: the §5.2 budget rule no longer binds. The candidate list covers 2006 onward, and the labelled-window start is to be revisited before `prereg-v1`.
  - **D41**: added dependencies typer, python-dotenv and respx (test only). DuckDB is pinned below 2 because 2.0.0 was released on 2026-10-21.
- [X] T042 [P] Write `README.md`: a one-line purpose, setup (`uv sync`, and a `.env` with `SEC_USER_AGENT="Name email"` and `TIINGO_API`), the commands implemented so far, and links to `docs/initialplan.md` and `specs/001-skeleton-sec-ingest/quickstart.md`.
- [X] T043 Run `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` (offline) until all pass. Then run `uv run pytest --run-network tests/network` once.
- [X] T044 Walk through `specs/001-skeleton-sec-ingest/quickstart.md` end to end, and record each step's outcome in `specs/001-skeleton-sec-ingest/run-notes.md`. Include the secrets scan, `git log -p | grep -c "<TIINGO key>"` = 0 (SC-009).
- [ ] T045 With the researcher's approval, commit on branch `001-skeleton-sec-ingest` in small logical commits: setup, foundation, US1, US2, US3, docs. Never commit `data/` or `.env`.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (T001–T005)**: no dependencies. T003 and T004 can run in parallel after T002.
- **Foundational (T006–T009)**: needs Setup. T008 can run in parallel with T006 and T007. T009 needs T007 (logging filter). **Blocks every story.**
- **US1 (T010–T018)**: needs Foundational.
- **US2 (T019–T033)**: needs Foundational for the code. T027 onward needs **real data from T018** to run, though the unit tests use fixtures only. T024 also needs `manifest.py` (T015) and `http.py` (T014).
- **US3 (T034–T040)**: needs Foundational only, so it can run in parallel with US1 and US2.
- **Polish (T041–T045)**: after the stories you want shipped.

### Within each story

Tests first (they must fail), then modules, then CLI wiring, then the real run.
- **US1**: T014 → T016 → T017 → T018. T015 can run in parallel with T014.
- **US2**: T026 → T027 → T028 → T029 → T031 → T032 → T033. T024 → T025, and T030, can run in parallel with T026–T029.

### Critical path (deadline 27 Oct)

T001 → T002 → T005 → T006 → T007 → T009 → T014 → T016 → T017 → **T018 (start the download as early as possible)** → T026 → T027 → T028 → T029 → T031 → T032 → **T033**

---

## Parallel Examples

```bash
# US1: write the tests together
Task: "tests/unit/test_http.py (T010)"
Task: "tests/unit/test_manifest.py (T011)"
Task: "tests/unit/test_sec_bulk.py (T012)"
# then the two independent modules together
Task: "src/sentinel/ingest/http.py (T014)"
Task: "src/sentinel/ingest/manifest.py (T015)"

# US2: while the download (T018) runs
Task: "tests T019–T023"
Task: "src/sentinel/ingest/sec_tables.py (T026)"
Task: "src/sentinel/provisional/tiingo_list.py (T030)"
Task: "src/sentinel/ingest/sec_reference.py (T024)"

# US3: independent of US1/US2 at any time after Phase 2
Task: "T034–T038 (all [P] test files)"
```

---

## Implementation Strategy

### MVP first (US1)

1. Phases 1 and 2 (T001–T009).
2. US1 (T010–T017), then **T018: start the real download straight away**. It runs while US2's code is written.
3. Validate: `verify-sec` reports `ok=83`.

### Incremental delivery

1. US2 on the real archive. Freeze the candidate list by 27 Oct (SC-008).
2. US3 (the register check, `check`, the guards) can be done in any gap, but must be finished before merging.
3. Polish: decision log, README, quickstart walk-through, commits.

### Notes

- **Constitution amendment**: amending Principle VI ("free sources only") for the one-month Tiingo Power plan is **not part of this feature**. Do it with `/speckit-constitution` before planning the price-pull feature.
- **Verbatim register cells**: the Appendix E strings in `params.yaml` must stay character-for-character identical to the plan, so any edit to Appendix E must be mirrored there (T034 enforces this).
- **Data at rest**: no task writes Tiingo data to disk. `tiingo_list.py` works on bytes in memory.
