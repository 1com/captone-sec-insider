# EDGAR-SENTINEL

Do clusters of insider purchases (SEC Form 4) predict stock returns after trading costs? This is a research pipeline first and a screener second. The full design is in [docs/initialplan.md](docs/initialplan.md), and the project rules are in [.specify/memory/constitution.md](.specify/memory/constitution.md).

## Setup

```bash
uv sync
```

Create a `.env` file in the repository root. It is git-ignored and never committed.

```
SEC_USER_AGENT="Your Name your@email"   # required by the SEC's fair-access policy
TIINGO_API=...                          # Tiingo key (delisted-stock prices)
```

Check the setup (works offline):

```bash
uv run sentinel check
```

## Commands available so far

| Command | Plan step | What it does |
|---|---|---|
| `sentinel check` | 0 | Checks `.env`, `config/params.yaml` against Appendix E, and the data folders |
| `sentinel fetch-sec` | 1 | Downloads the 83 quarterly SEC insider data sets (2006 Q1 – 2026 Q3, about 0.9 GB) into `data/raw/sec/insider/`, recording a SHA-256 for each in `data/raw/manifest.jsonl`. Resumable; at most 10 requests per second |
| `sentinel verify-sec` | 1 | Re-hashes the stored archives against the manifest (offline) |
| `sentinel fetch-sec-tickers` | 6 (partial) | Saves today's SEC company-ticker map |
| `sentinel candidates-provisional` | 5 (provisional) | Ranks likely-delisted companies whose prices must come from Tiingo. Look-ahead, used only to plan the price pull; output goes to `data/provisional/` |
| `sentinel stage` | 2 | Loads every table of every quarter into typed staging tables in `data/warehouse.duckdb` (37.9 M rows, about 4 min) |
| `sentinel entities` | 3 | Point-in-time insider entities (co-filers count as one buyer) and roles |
| `sentinel gates` | 4 | Gate flags on every trade line, clean purchases (at least $25,000 per filing) with holdings, and the funnel |
| `sentinel detect-prelim` | 5 | Preliminary events: clusters (A), solo CEO/CFO (B1) and solo officer or director (B2) |
| `sentinel compare-provisional` | QA | Compares the events with feature 001's; writes `specs/002-insider-warehouse/comparison.md` |
| `sentinel symbols [--tiingo-report]` | 6 | Maps every company to price tickers from SEC data; optionally counts matches in Tiingo's public list, in memory |
| `sentinel fetch-headers` | 6 | Downloads each signal filing's EDGAR header (industry code, acceptance time). Resumable; a few hours |
| `sentinel fetch-prices --source yahoo\|tiingo` | 7 | Daily prices: Yahoo for listed companies, SPY and IWM (from 2010); Tiingo for delisted ones, **only during the paid month** (exit 6 otherwise). Raw files under `data/raw/yahoo/` and `data/raw/tiingo/` |
| `sentinel fetch-reference` | 7 | Kenneth French factors, industries, SIC definitions and size breakpoints; FINRA's tick-size pilot file |
| `sentinel fetch-company` | 8–9 | The SEC's bulk `companyfacts.zip` and `submissions.zip` (about 3 GB, two requests) |
| `sentinel prices` | 7 | One as-traded price series per company, and the market calendar |
| `sentinel reference` | 7 | Loads the French and FINRA files |
| `sentinel company-facts` | 8–9 | Company profiles, filing histories and first-filed XBRL facts |
| `sentinel detect [--fetch-missing-headers]` | 7 | Final events: price check G8, issuer-type rule G7, the $2 / liquidity / activity floors, 63-session cooldown, market cap at T |
| `sentinel delistings` | 8 | Classifies early-ending price series (acquired / performance / unknown) and assigns delisting returns |
| `sentinel costs` | 10 | Spread and round-trip cost per event; writes `specs/004-market-data-events/costs.md` |
| `sentinel coverage` | QA | Writes `specs/004-market-data-events/coverage.md` (price coverage, G8 rate, outcomes) |
| `sentinel tiingo-status`, `sentinel tiingo-delete [--yes]` | 7 | The Tiingo deletion register; deletion when the paid month ends |
| `sentinel build` | 2–10 | Rebuilds the whole warehouse from `data/raw/` (no network) and checks its invariants |
| `sentinel audit sheets\|summary\|no-sic` | QA | Hand-audit sheets and their scores; `no-sic` is the D45 check |
| `sentinel audit golden\|delistings\|market-caps` (+ `-summary`) | QA | Feature 004 audits: 30 events against EDGAR, 30 delisting classes, 10 market caps |
| `sentinel explore` | — | Opens the warehouse read-only in the DuckDB UI at http://localhost:4213 ([docs/explore.md](docs/explore.md)) |
| `sentinel lookup` | 19 (product v1) | Builds `data/lookup.duckdb` for the stock lookup from SEC tables only (no prices; about 35 s). Rerun after every warehouse rebuild |
| `sentinel serve [--port 8766]` | 19 (product v1) | Stock lookup at http://127.0.0.1:8766: search by ticker, name or CIK; every insider transaction with plain-English codes, holdings over time, insider-buying events, glossary; JSON at `/api/issuers/search` and `/api/issuers/{cik}/transactions` ([specs/005-stock-lookup/quickstart.md](specs/005-stock-lookup/quickstart.md)) |

`uv run sentinel --help` lists every pipeline step. Steps not built yet exit with code 4.

## MVP prototype (feature 003)

A self-contained prototype in `mvp/` that shows what the product will look like. It is governed by the constitution's Prototype Exception: returns are computed only for 2006–2011 pilot events, at companies still listed today, and every result is labelled as such.

```bash
uv run python -m mvp build --skip-prices   # about 30 s with cached data (drop the flag to refresh prices)
uv run python -m mvp serve                 # http://127.0.0.1:8765
uv run python -m mvp check                 # constitution guards
```

Seven tabs: new insider buying (the screener, shown first), does it work? (overview), findings (event study), model, score & features (the score's definition, every input and what each model learned), company lookup, and method & limits. The public copy is at https://1com.github.io/captone-sec-insider/. A 5-minute class walkthrough is in [mvp/DEMO.md](mvp/DEMO.md); results and decisions are in [specs/003-mvp-dashboard/run-notes.md](specs/003-mvp-dashboard/run-notes.md).

## Data layout

Everything under `data/` is git-ignored and can be regenerated:

- `data/raw/`: downloads exactly as received, read-only, recorded in `manifest.jsonl`.
- `data/provisional/`: the provisional candidate list and its summary against the pilot.
- `data/mvp/`: the MVP's own downloads (Yahoo prices, SEC company records), work tables and the built dashboard.
- `data/raw/tiingo/`: delisted-stock prices, stored **only while the paid Tiingo plan is active** and deleted when it ends (`sentinel tiingo-delete`; constitution VI).
- `data/warehouse.duckdb`: the analysis database (schemas `stg`, `core`, `evt`, `audit`), rebuilt from `data/raw/` by `sentinel build`. Browse it with `sentinel explore` or DBeaver (read-only); see [docs/explore.md](docs/explore.md).

## Development

```bash
uv run pytest            # offline; network tests need --run-network
uv run pytest -m slow    # against the real data/warehouse.duckdb
uv run ruff check .
```

Heavy data steps run under a memory ceiling, e.g. `systemd-run --user --wait -p MemoryMax=5G … uv run sentinel build`, so a runaway step cannot take down WSL. Features follow spec-kit: `specs/<feature>/` holds each feature's spec, plan, tasks and run notes. The schedule is in [docs/planning/](docs/planning/README.md).
