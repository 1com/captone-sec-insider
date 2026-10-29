# EDGAR-SENTINEL v2: architecture

How the data is stored and flows, layer by layer. What the platform does is in [spec.md](spec.md).

## Overview

```text
 sources ─► 1 RAW ─► 2 STAGING ─► 3 REFERENCE + CORE ─► 4 FEATURES ─► 5 LABELS, MODELS, SCORES ─► 6 SERVING
           files as   one complete   companies, securities,  one row per     answers (dev only),    what the
           downloaded table per      tickers; prices,        security per    model registry, daily  app reads
           (immutable) source        filings, financials,    trading day     scores and outcomes    (read-only
                                     insiders (known_at)                                            snapshot)
```

| Where | What | Written by |
|---|---|---|
| `data/raw/<source>/…` + `data/raw/manifest.jsonl` | layer 1, files as downloaded, never edited | the fetch commands and `sentinel update` |
| `data/sentinel.duckdb` | layers 2–5, one schema per layer or source | the build and `sentinel update` (one writer at a time) |
| `data/serving.duckdb` | layer 6, a read-only copy published after each build or update | `sentinel publish` |
| `data/exports/` | Parquet snapshots for sharing (private: Tiingo-derived) | `sentinel export` |
| `data/mlflow.db` | model runs | the model commands |

One build database instead of v1's two (warehouse and panel): v1 split them to protect the
pre-registered insider study, which v2 drops (V2-4). The risk holdout is protected by the label code
instead (layer 5). Everything readers use comes from `serving.duckdb`, so a browsing session never
locks the database the daily update writes (a v1 problem, see lessons).

## Layer 1: raw

Files exactly as downloaded, read-only, one manifest line each (path, source, key, URL without
secrets, fetched at, bytes, SHA-256). The v1 files are kept as they are (V2-3). New downloads from
the daily update are stored by date: `data/raw/<source>/daily/<YYYY-MM-DD>/…`.

| Source folder | Format | Content |
|---|---|---|
| `sec/insider/` | zip of tab-separated tables, per quarter | Form 4 data sets 2006 Q1 – 2026 Q3 |
| `sec/company/` | zip of JSON | `submissions.zip` (every filer's filings), `companyfacts.zip` (financial facts) |
| `sec/headers/` | text | filing headers (industry code at the time of a filing) |
| `sec/reference/` | JSON | the SEC company–ticker list, one snapshot per day from now on |
| `yahoo/`, `yahoo/panel/` | Parquet per ticker | daily prices |
| `tiingo/{prices,panel_prices,listed_prices}/`, `…meta/`, `panel_search/`, `supported_tickers.zip` | gzip CSV / JSON | daily prices, ticker metadata, name searches, Tiingo's ticker list |
| `fred/`, `cboe/`, `finra/`, `french/` | JSON / CSV / text | macro, VIX, short volume, factors |

## Layer 2: staging (one schema per source)

Each table holds **everything** downloaded from its source, typed (dates, numbers, flags), with
`raw_file` and `raw_row` on every row. Values that fail to convert are logged in
`stg_audit.conversion_issue`, never dropped silently. Large sources are views over the raw files
(DuckDB reads Parquet and gzip CSV directly), so staging costs no extra disk.

| Schema | Tables |
|---|---|
| `stg_sec_form4` | `submission`, `reporting_owner`, `nonderiv_trans`, `nonderiv_holding`, `deriv_trans`, `deriv_holding`, `footnote`, `owner_signature` |
| `stg_sec_filings` | `filer` (one row per CIK: names, SIC, entity type, tickers), `filing` (every filing: form, dates, 8-K items) |
| `stg_sec_xbrl` | `fact` (every reported value, every version, with its filing date and accession) |
| `stg_sec_tickers` | `snapshot` (each day's company–ticker list) |
| `stg_sec_headers` | `header` |
| `stg_yahoo` | `price` (every ticker downloaded), `action` (splits, dividends) |
| `stg_tiingo` | `price`, `meta`, `listing`, `search` |
| `stg_fred`, `stg_cboe`, `stg_finra`, `stg_french` | one table each |

## Layer 3: reference and core

### Reference (the backbone)

| Table | One row per | Key columns |
|---|---|---|
| `ref.company` | company (CIK) | names over time, SIC, `filer_type` (us / foreign / non_reporting), `is_fund` (registered fund reports N-CSR, NPORT, N-CEN, or a fund or blank-check SIC), entity type |
| `ref.security` | traded security | `security_id`, `cik`, `kind` (common, class A/B, ADR, preferred), `adr_ratio` where known, `primary` flag |
| `ref.ticker_history` | ticker and period | `security_id`, `ticker`, `exchange`, `valid_from`, `valid_to`, `evidence` (SEC snapshot, Form 4 symbol, Tiingo listing, name search) |
| `ref.calendar` | trading day | session number |
| `ref.industry` | SIC range | Fama–French 12 sector |
| `ref.coverage` | security, question and day | `level` (full / foreign / price_only), `eligible`, `reason` |

The universe is `ref.security`: built from what trades (SEC snapshots, Tiingo's listing of dead
tickers, Form 4 symbols), not from any one dataset.

### Core (one clean, source-independent version of each fact; every row has `known_at`)

| Table | One row per | Notes |
|---|---|---|
| `core.price_daily` | security and session | open, high, low, close, volume, adjusted close, split factor, dividend, dollar volume, `source`, `glitch` |
| `core.price_choice` | security | which source covers which dates and why: Yahoo first, Tiingo where Yahoo is missing or starts late, Tiingo only for disappeared securities; the name and date checks |
| `core.price_check` | security and session | Yahoo against Tiingo where both exist |
| `core.corporate_action` | event | splits, dividends, ADR ratio changes, delistings with their reason (merger, failure) |
| `core.filing` | filing | acceptance time, form, 8-K items, period |
| `core.financial_fact` | company, item, period and version | value, unit, `known_at`, `first_filed` flag; v1's item list and fallbacks |
| `core.shares_outstanding` | security and date | per class; cover-page count, else quarterly basic average; ADR ratio applied |
| `core.results_release` | release | announcement rule of risk_params v5: item 2.02 8-Ks within 5 days are one announcement; the last per 10-Q or 10-K (filed from 5 days before to 75 after) is the release; `known_at` = later of release and report |
| `core.insider_trade` | Form 4 line | the v1 gates (open-market purchase or sale, common stock, not planned, not in an offering, timely) as flags |
| `core.insider_entity`, `core.insider_cluster` | person or entity; cluster | merged identities and roles; clusters of buyers (tracker) |
| `core.macro_observation` | series and period | value with its release date |
| `core.short_volume_daily` | security and session | FINRA short and total volume |

## Layer 4: features

`feature.daily`: one row per covered security per trading day, the v1 feature families (price,
financial statements, company events, insider, short selling, macro, sector) computed as of that
day's close. Built incrementally: each update adds one day; a rebuild recomputes everything. The
month-end rows are the training panel. `feature.definition` versions the feature set.

## Layer 5: labels, models, scores

| Table | Content |
|---|---|
| `label.volatility`, `label.dilution`, `label.results_move` | answers for development only: computed only for windows that end by 31 December 2022; the code refuses later windows until the one holdout run |
| `model.registry` | model version, risk, training data version, test results, status (live / candidate / retired), MLflow run |
| `score.daily` | every forecast every day: security, risk, model version, value, band, coverage level; append only |
| `score.outcome` | each forecast's outcome once its window closes: the live hit rates |

## Layer 6: serving

`data/serving.duckdb`, rebuilt by `sentinel publish` after every build or update and opened
read-only by the app and by anyone exploring:

| Table | Feeds |
|---|---|
| `app.stock` | the stock page header and search |
| `app.company_card` | latest facts, financials, red flags, next results date, the three forecasts with bands |
| `app.filings`, `app.insider_activity` | the timeline and the insider tracker |
| `app.risk_screener`, `app.insider_feed` | the screeners |
| `app.model_card` | test and live hit rates |

## Commands

| Command | Does |
|---|---|
| `sentinel fetch <source>` | download raw files (the v1 fetchers, unchanged in behaviour) |
| `sentinel build [layer]` | rebuild layers 2–5 from raw |
| `sentinel models` | evaluate and fit the risk models (D60 rules), write the report |
| `sentinel update` | the daily increment: fetch, extend, score |
| `sentinel publish` | write `serving.duckdb` |
| `sentinel export` | Parquet snapshot for sharing |
| `sentinel serve` | the web app |

## Conventions

- Keys: `cik` as text without leading zeros; `security_id` as `<cik>:<class>`; dates as `DATE`.
- Every table has a test with synthetic rows and a check on named real cases.
- Python 3.14, uv, DuckDB, pandas, LightGBM, scikit-learn, MLflow, Typer, FastAPI; ruff (100
  columns), pytest.
