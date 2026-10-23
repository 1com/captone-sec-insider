# Contract: CLI Additions (Feature 004)

Extends [../../002-insider-warehouse/contracts/cli.md](../../002-insider-warehouse/contracts/cli.md).

**Exit codes**:
- 0 ok;
- 1 failed or problems found;
- 2 usage;
- 3 config, **or missing inputs that another command must fetch first** (for example headers);
- 4 not implemented;
- 5 SEC 403;
- 6 **outside the Tiingo paid window** (new).

The stubs `fetch-prices`, `fetch-reference`, `detect`, `delistings` and `costs` are implemented. `shares-out` is replaced by `fetch-company` and `company-facts`.

## Fetch commands (network; write only `data/raw/` and the manifest)

| Command | Step | Fetches | Writes | Rate / guard |
|---|---|---|---|---|
| `sentinel fetch-prices --source yahoo` | 7 | Yahoo-mapped tickers of issuers with preliminary events from `rules.final_detection_start`, plus `ops.reference_symbols` (SPY, IWM), from `rules.price_history_start` | `data/raw/yahoo/{ticker}.parquet`, `failures.csv` | Batches of `ops.yahoo_batch_size` (50); a pause between batches; up to 3 retries |
| `sentinel fetch-prices --source tiingo` | 7 | `supported_tickers.zip` (once); then meta and prices for each resolved ticker, fill-in and Yahoo fallback | `data/raw/tiingo/…` (gzip), manifest `source = tiingo` | **Refuses (exit 6) outside `[ops.tiingo_paid_from, ops.tiingo_paid_until)`**; `ops.tiingo_requests_per_second` (2) |
| `sentinel fetch-reference` | 7 | French library files (`ops.french_files`), FINRA `TSPilotChanges.txt` | `data/raw/french/`, `data/raw/finra/` | Polite single requests |
| `sentinel fetch-company` | 9 | SEC `companyfacts.zip`, `submissions.zip` | `data/raw/sec/company/` | SEC limiter (shared), contact User-Agent; stop on 403 (exit 5) |
| `sentinel fetch-headers --final` | 7 | Signal filings of `needs_header` candidates (includes the warm-up from 2011-07-01) | as feature 002 | as feature 002 |

**Options common to the fetch commands**:
- `--limit N`: fetch at most N items (testing);
- `--retry-failures`: retry earlier failures.

**Resume**: reruns skip anything already in the manifest.

**Progress**: printed every 250 items.

## Build commands (offline; idempotent; append to `core.build_log`)

| Command | Step | Reads | Writes |
|---|---|---|---|
| `sentinel prices` | 7 | Yahoo and Tiingo raw files; `core.symbol_map`; `evt.prelim_event`; `core.filing` | `stg.price_yahoo`, `stg.price_tiingo`, `core.tiingo_listing`, `core.price_series`, `core.price_daily`, `core.session`, `audit.price_issue` |
| `sentinel reference` | 7 | `data/raw/french/`, `data/raw/finra/` | `core.ff_factor_daily`, `core.ff_industry_daily`, `core.sic_industry`, `core.me_breakpoint`, `core.tick_pilot` |
| `sentinel company-facts` | 9 | `data/raw/sec/company/*.zip` (universe members only) | `core.issuer`, `core.company_filing`, `core.xbrl_fact` |
| `sentinel detect [--fetch-missing-headers]` | 7 | `core.transaction`, `core.price_daily`, `core.session`, `core.filing_header`, `core.issuer`, `core.xbrl_fact`, entities and roles | `core.price_check`, `core.priced_purchase`, `evt.event_candidate`, `evt.event`, `evt.event_member`, `audit.event_funnel`, `audit.price_coverage`, `audit.g8_rate` |
| `sentinel delistings` | 8 | `core.price_series`, `core.price_daily`, `core.session`, `core.company_filing`, `core.tiingo_listing`, `core.issuer` | `core.delisting` |
| `sentinel costs` | 10 | `evt.event`, `core.price_daily`, `core.tick_pilot` | `evt.event_cost`, `specs/004-market-data-events/costs.md` |
| `sentinel coverage` | QA | the audit tables, `core.delisting`, `core.xbrl_fact` | `specs/004-market-data-events/coverage.md` (SC-001, SC-002, unpriced counts by year and group, XBRL coverage per item, delisting classes) |
| `sentinel build` | 2–10 | as above | Runs feature 002's steps, then `prices`, `reference`, `company-facts`, `detect`, `delistings`, `costs`, invariants. Steps whose raw inputs are absent are skipped with a note |

**`detect` behaviour**:
- Signal filings without a stored header make it exit 3 with their count and the hint `sentinel fetch-headers --final`.
- `--fetch-missing-headers` instead fetches them and reruns, at most 3 rounds. It is never used by `build`.
- It prints the G8 rate, events by group and outcome, and coverage for A and B1 events from 2012.
- It exits 1 if an invariant on its tables fails.

## Audit commands

| Command | Writes | Notes |
|---|---|---|
| `sentinel audit golden [--force]` | `specs/004-market-data-events/audits/golden_set.csv` | 30 events, seed 20261025 |
| `sentinel audit golden-summary` | prints agreement | exit 1 while verdicts are blank |
| `sentinel audit delistings [--force]` | `…/audits/delisting_audit.csv` | 30 issuers, 10 per class, seed 20261024 |
| `sentinel audit delistings-summary` | prints agreement per class | exit 1 while verdicts are blank |
| `sentinel audit market-caps` | `…/audits/market_caps.csv` | First run fetches Yahoo's market cap for the 10 companies in `ops.market_cap_examples` and stores it raw; later runs are offline |

## Tiingo register commands

| Command | Effect |
|---|---|
| `sentinel tiingo-status` | Lists the registered raw files (count, bytes) and rows per registered table, the paid window and the days left. Exit 1 if any Tiingo data lies outside the register |
| `sentinel tiingo-delete --yes` | Runs the deletion in [tiingo-register.md](tiingo-register.md). Without `--yes` it prints what would be deleted and exits 2 |
