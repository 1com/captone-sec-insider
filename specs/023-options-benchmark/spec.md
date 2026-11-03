# Feature Specification: 023 Options Benchmark & On-Demand Option Chains

## 1. Objective & User Need
The researcher requires the ability to fetch option prices and chains for any US-traded stock on demand.
Specifically:
1. Fetch all available option expirations for the stock over the next 365 days (1 year).
2. Collect full contract data (Calls and Puts across all strike prices).
3. Store raw snapshots in `data/raw/options/` with SHA-256 manifest lines.
4. Stage and structure the option contracts into DuckDB (`core.option_chain` and `serving.duckdb`) in clean relational tables.
5. Provide on-demand access via CLI (`sentinel fetch options <ticker>`) and API (`/api/options/{ticker}`).
6. Compute market-implied benchmarks: At-The-Money 3-month implied volatility ($IV_{63}$) and next-earnings implied straddle move.

## 2. Requirements & Behavior
- **Data Source**: Yahoo Finance via `yfinance.Ticker.options` and `yfinance.Ticker.option_chain(expiration)`.
- **Scope**: All expirations $\le 365$ calendar days from the fetch date.
- **Contract Schema**:
  - `ticker`: Stock symbol (e.g. `AAPL`).
  - `as_of`: Snapshot fetch date (`YYYY-MM-DD`).
  - `expiration`: Option contract expiration date (`YYYY-MM-DD`).
  - `days_to_exp`: Calendar days from `as_of` to `expiration`.
  - `option_type`: Contract type (`call` or `put`).
  - `strike`: Contract strike price.
  - `last_price`: Last executed transaction price.
  - `bid`: Current bid price.
  - `ask`: Current ask price.
  - `mid_price`: Midpoint `(bid + ask) / 2` (or `last_price` if bid/ask absent).
  - `volume`: Daily contract volume.
  - `open_interest`: Outstanding contracts.
  - `implied_volatility`: Implied volatility computed by options market pricing models.
  - `in_the_money`: Boolean flag (`ITM`).
  - `contract_symbol`: Standard OCC symbol (e.g. `AAPL261120C00230000`).
- **Idempotency & Deduplication**: Re-running on the same day updates or replaces the snapshot for that `(ticker, as_of)`.
- **Zero-Data / Fallback Mode**: When running in CI without network/data, mock or synthetic option data is returned gracefully.
