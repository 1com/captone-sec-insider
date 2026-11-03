# Implementation Plan: 023 Options Benchmark

## Phases
1. **Fetcher Implementation (`src/sentinel/fetch/options.py`)**:
   - `fetch_option_chain(ticker, max_days=365, as_of=None) -> pd.DataFrame`
   - Retrieve all expiration dates within `max_days`.
   - Download calls and puts for each expiration.
   - Standardize column names and compute `mid_price` and `days_to_exp`.
   - Persist to `data/raw/options/{date}/{ticker}.parquet` and record manifest line.

2. **Core Database Integration (`src/sentinel/core/options.py`)**:
   - Create table `core.option_chain` in DuckDB.
   - Ingest fetched DataFrame with deduplication on `(ticker, as_of, expiration, option_type, strike)`.
   - Compute ATM implied volatility for 30d, 60d, 90d tenors.

3. **CLI & Web API Integration**:
   - CLI: `sentinel fetch options <ticker> [--days 365]`
   - Web API: `GET /api/options/{ticker}` returning both summary and detailed chains.
   - UI Panel: Option chains display on stock detail view (`/stock/{ticker}`).

4. **Testing & Validation**:
   - Unit tests mocking `yfinance` to test parsing, database insertion, and calculations.
   - Smoke test against a live symbol (`AAPL`).
