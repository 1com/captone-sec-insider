# Data Model: 023 Options Chain & Market Benchmarks

## 1. Storage Layers

### Layer 1: Raw File Snapshot
- **Path**: `data/raw/options/{date}/{ticker}.parquet`
- **Manifest**: Appended to `data/raw/manifest.jsonl` with SHA-256 and byte count.

### Layer 3: Core Database Table (`core.option_chain`)
In `data/sentinel.duckdb` (and serving copy):

```sql
CREATE TABLE IF NOT EXISTS core.option_chain (
    ticker VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    expiration DATE NOT NULL,
    days_to_exp INTEGER NOT NULL,
    option_type VARCHAR NOT NULL, -- 'call' | 'put'
    strike DOUBLE NOT NULL,
    last_price DOUBLE,
    bid DOUBLE,
    ask DOUBLE,
    mid_price DOUBLE,
    volume BIGINT,
    open_interest BIGINT,
    implied_volatility DOUBLE,
    in_the_money BOOLEAN,
    contract_symbol VARCHAR,
    PRIMARY KEY (ticker, as_of, expiration, option_type, strike)
);

CREATE INDEX IF NOT EXISTS idx_option_chain_lookup
ON core.option_chain (ticker, as_of, expiration);
```

### Layer 6: Serving View / Table (`app.option_summary`)
```sql
CREATE TABLE IF NOT EXISTS app.option_summary (
    ticker VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    spot_price DOUBLE,
    atm_iv_30d DOUBLE,
    atm_iv_60d DOUBLE,
    atm_iv_90d DOUBLE,   -- 3M benchmark for Volatility Model 005
    next_results_straddle_move DOUBLE, -- benchmark for Model 006
    call_volume BIGINT,
    put_volume BIGINT,
    put_call_ratio DOUBLE,
    PRIMARY KEY (ticker, as_of)
);
```
