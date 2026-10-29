# EDGAR-SENTINEL v2: architecture

How the data is stored and flows, layer by layer. What the platform does is in [spec.md](spec.md).

## Overview

```text
 sources ─► 1 RAW ─► 2 STAGING ─► 3 REFERENCE + CORE ─► 4 FEATURES ─► 5 LABELS, MODELS, SCORES ─► 6 SERVING
           files as   one complete   companies, securities,  as of chosen    answers (dev only),    what the
           downloaded table per      tickers; prices,        days: month-    model registry, daily  app reads
           (immutable) source        filings, financials,    ends, release   scores and outcomes    (read-only
                                     insiders (known_at)     eves, latest                           snapshot)
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
its raw file on every row (`raw_file`; for Form 4, `quarter` and `src_row`). Form 4 values that fail
to convert are logged in `stg_sec_form4.conversion_issue`, never dropped silently.

| Schema | Tables |
|---|---|
| `stg_sec_form4` | `submission`, `reportingowner`, `nonderiv_trans`, `nonderiv_holding`, `deriv_trans`, `deriv_holding`, `footnotes`, `owner_signature`; `load_report`, `conversion_issue` |
| `stg_sec_filings` | `filer` (one row per CIK: names, former names, SIC, entity type, tickers), `filing` (every filing of a company-like filer: form, dates, 8-K items) |
| `stg_sec_xbrl` | `fact` (every reported value of the items used, every version, with its filing date and accession) |
| `stg_sec_tickers` | `snapshot` (the SEC company–ticker lists) |
| `stg_sec_headers` | `header` (acceptance time, SIC at the filing), `parse_failure` |
| `stg_yahoo` | `price` (every ticker downloaded, with dividends and splits) |
| `stg_tiingo` | `price`, `meta`, `listing`, `search` (Tiingo's `[]` answers, tickers without prices, are counted and skipped) |
| `stg_market` | `fred` (market series; CPI and unemployment as first released), `vix`, `short_volume` (FINRA, summed over facilities), `sic_industry` |

## Layer 3: reference and core

### Reference (the backbone)

| Table | One row per | Key columns |
|---|---|---|
| `ref.company` | company (CIK) | names and former names, SIC, `filer_type` (us / foreign / non_reporting), `is_fund` (registered fund reports N-CSR, NPORT, N-CEN since 2012, or a fund SIC), `is_blank_check`, first and last periodic report, Form 4 span, today's tickers |
| `ref.ticker_history` | company, ticker and period | `cik`, `ticker`, `exchange`, `valid_from`, `valid_to`, `evidence` (Form 4 symbol, SEC list) |
| `ref.calendar` | trading day | `session_no` (SPY's sessions since 2010) |
| `ref.sector` | company | Fama–French 12 sector from the SIC code |
| `ref.security` | priced company | `security_id` (= `cik`: one priced series per company), ticker, source, listed today, first and last price day, `coverage` (full / foreign / price_only) |

Companies come from SEC filings (every company-like filer and every Form 4 issuer); a company is
priced when a ticker and a price series pass the identity checks (`core.price_choice`). Share
classes and ADR ratios are not modelled yet, so a foreign filer's market value is left missing.

### Core (one clean, source-independent version of each fact, with `known_at`)

`known_at` is the trading day from whose close a fact may be used: the next session after its
filing date, or the filing date itself when its header shows acceptance before the 4 pm close.

| Table | One row per | Notes |
|---|---|---|
| `core.price_candidate` | company and candidate series | every Yahoo or Tiingo series a company could be priced from, with the identity check |
| `core.price_choice` | company | the chosen source and ticker and why: Yahoo first; Tiingo where Yahoo is missing or starts late, and for disappeared companies; trim dates |
| `core.price_daily` | company and session | as-traded open, high, low, close, volume; adjusted close; `cum_split_after`; dividend; dollar volume; `source`; `glitch` |
| `core.price_issue` | rejected price row | close at or below zero, high below low, a day that is not a session |
| `core.price_check` | company | Yahoo against Tiingo where both exist (agree / partly / mismatch) |
| `core.filing` | filing | form, filing and report dates, 8-K items, acceptance time from the header, `known_at` |
| `core.financial_fact` | company, item, period and version | value, unit, `first_filed`, `known_at`; v1's item list and tag fallbacks; impossible dates left out (V2-15) |
| `core.shares_outstanding` | company and date | the cover-page count as first filed, else the quarterly basic average |
| `core.results_release` | release | announcement rule of risk_params v5: item 2.02 8-Ks within 5 days are one announcement; the last per 10-Q or 10-K (filed from 5 days before to 75 after) is the release; `confirmed` = later of release and report |
| `core.insider_filing` | Form 3, 4 or 5 | issuer, form, filing date, `known_at` |
| `core.insider_entity_member`, `core.insider_owner_role` | membership change; role interval | co-filers are one entity from their joint filing on; roles (CEO/CFO, officer, director, 10% owner) over time |
| `core.insider_trade` | Form 4 line | v1's gates as flags; `side` (buy / sell), `open_market`, `planned` |
| `core.insider_activity` | filing and side | the tracker's row: value, shares, entity and role, plan and offering flags, holdings before and after, `clean` purchase (V2-14) |
| `core.insider_funnel` | quarter and gate | purchase lines through each gate |
| `core.insider_cluster` | company, day and group | A (several buyers), B1 (a CEO or CFO), B2 (an officer or director); `starts_event` after the cooldown (`config/tracker.yaml`) |
| `core.macro_observation` | series and period | value, release date, `known_at` |
| `core.ticker_span` | company, ticker and period | v1's rules for symbol-keyed data |
| `core.short_volume` | company and session | FINRA short and total volume over the company's symbols |

## Layer 4: features

`feature.row` lists the (company, day) rows that features are computed for, each as of that day's
close (V2-13): month-ends from 2012 (the volatility and dilution training panel), the close before
each results release (the results-move training rows) and each company's latest day (the
product). Each family fills one table keyed by those rows: `feature.price`, `feature.fundamental`,
`feature.event`, `feature.insider`, `feature.short`, and `feature.macro` (per day). `feature.snapshot`
joins them with sector, coverage and the panel's row rules: `active_filer`, `excluded` (funds,
blank-check companies) and `eligible` (the rows the models learn from); a foreign filer's insider,
8-K and market-value features are missing, not zero. Definitions are in `src/sentinel/features/`.

## Layer 5: labels, models, scores

| Table | Content |
|---|---|
| `label.volatility`, `label.dilution` | per month-end row: the registered answer and the date its window ends; development only (windows ending by 31 December 2022); the step refuses to run unless `config/risk_params.yaml` equals its `prereg-risk-v5` version |
| `label.results_move` | per results release: the market-adjusted move, the mean of the previous four (the naive baseline); `as_of` is the release-eve row its features come from |
| `model.registry` | model version, risk, training data version, test results, status (live / candidate / retired), MLflow run (next step) |
| `score.daily` | every forecast every day: security, risk, model version, value, band, coverage level; append only (next step) |
| `score.outcome` | each forecast's outcome once its window closes: the live hit rates (next step) |

## Layer 6: serving

`data/serving.duckdb`, rebuilt by `sentinel publish` after every build or update and opened
read-only by the app and by anyone exploring:

| Table | Feeds |
|---|---|
| `app.stock` | the stock page header and search: every company with prices, periodic reports or Form 4s |
| `app.price_daily` | the price chart (with the source: Tiingo rows are for private use only) |
| `app.company_card` | the latest feature snapshot per priced company, the last results release and the expected next one; the three forecasts with bands join it once the models exist |
| `app.financials` | reported financial items per period, as first filed |
| `app.filings`, `app.insider_activity` | the timeline and the insider tracker, with EDGAR links |
| `app.screener`, `app.insider_feed` | the screeners and the market-wide insider events |
| `app.model_card` | test and live hit rates (once the models exist) |

`sentinel export` writes the same tables and one training set per risk question (`ml/volatility`,
`ml/dilution`, `ml/results_move`, features joined to their label; `ml/latest` for scoring) as
Parquet to `data/exports/`, with a generated `README.md` of files, rows and columns.

## Commands

| Command | Does |
|---|---|
| `sentinel fetch <source>` | download raw files (the v1 fetchers, unchanged in behaviour) |
| `sentinel build <layer> [--only steps]` | rebuild a layer from the one below: staging, reference, core, features, labels |
| `sentinel models` | evaluate and fit the risk models (D60 rules), write the report |
| `sentinel update` | the daily increment: fetch, extend, score |
| `sentinel publish` | write `serving.duckdb` |
| `sentinel export` | Parquet snapshot for sharing |
| `sentinel serve` | the web app |

## Conventions

- Keys: `cik` as text without leading zeros; `security_id` = `cik` (one priced series per company;
  share classes later); dates as `DATE`.
- Every table has a test with synthetic rows and a check on named real cases.
- Python 3.14, uv, DuckDB, pandas, LightGBM, scikit-learn, MLflow, Typer, FastAPI; ruff (100
  columns), pytest.
