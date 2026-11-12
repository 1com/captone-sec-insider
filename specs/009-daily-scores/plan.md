# Implementation Plan: Daily scores and live outcomes

**Branch**: `009-daily-scores` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/009-daily-scores/spec.md`

> **Amended 12 Nov 2026 (decision V2-72; feature 026, T018).** Gemini's version of 2 Nov scored
> all three questions with files from `data/models/` that the researcher never approved; it stayed
> paused (V2-42). It was redone: the update now makes the **dilution forecasts only** (the app shows
> no volatility or results-day forecast, V2-61) with the **frozen approved object the holdout test
> scored** (V2-59, loaded from MLflow, never from `data/models/`), stores every input's value and
> contribution with each forecast, registers the model as `approved` in `model.registry`, and
> publishes approved models' forecasts only. Outcomes wait for the first windows to close (May
> 2027). Where the text below disagrees, this note wins.

## Summary

Feature 009 connects the approved forecasting models (`results_move`, `dilution`, `volatility`) from `src/sentinel/models/` into the automated daily pipeline. Each weekday when `sentinel update` runs, it scores all active covered stocks into DuckDB table `score.daily`, checks past closed windows to compute realized results in `score.outcome`, and publishes the tables into `data/serving.duckdb` (schema `app`).

## Technical Context

- **Language/Version**: Python 3.14 (managed by `uv`).
- **Storage**: DuckDB 1.5+ (`data/sentinel.duckdb`, `data/serving.duckdb`), Parquet.
- **Memory Ceiling**: WSL2 10 GB system RAM; all heavy runs use `systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0`. DuckDB capped at 3 GB internally.
- **Testing**: `pytest -q`, `ruff check`, `ruff format`.
- **Target Platform**: Linux (WSL2 on Windows).
- **Constraints**: Point-in-time integrity (Principle I), zero look-ahead, holdout sealed (Principle II: 2023+ answers never read during training or tuning). Idempotent rerun: re-running on the same day must not duplicate records or fail `sentinel verify`.

## Constitution Check

- **Principle I (No Look-Ahead)**: Daily scoring on day $D$ reads only facts known at $D$'s close (`as_of <= D`). Model bundles are pre-trained on development data ($as\_of \le 2022-12-31$).
- **Principle II (Sealed Holdout)**: Daily scoring generates predictions for live and holdout dates, but does not use 2023+ target labels for model fitting.
- **Principle III (Raw Data Never Modified)**: Models and daily scores are derived layers (Layer 5 & 6) rebuilt deterministically from underlying core/feature tables.
- **Principle IV (Transparent Uncertainty)**: All scores must include risk bands (1 to 5) and calibrated probability ranges. Bare point forecasts alone are prohibited.

## Architecture & Data Flow

```
[sentinel update] 
       │
       ▼
 1. Core & Features Updated 
       │
       ▼
 2. scoring.daily.run() 
    ├─ Load latest feature snapshot (data/exports/latest.parquet or feature.snapshot)
    ├─ For each question (results_move, dilution, volatility):
    │   └─ Run model.predict(model, sub)
    └─ Append new records into score.daily in data/sentinel.duckdb
       │
       ▼
 3. scoring.outcomes.run()
    ├─ Scan open records in score.daily whose evaluation windows have closed
    ├─ Match against realized market returns, price volatility, or share changes
    └─ Record hits, errors, and outcomes into score.outcome
       │
       ▼
 4. serving.publish()
    └─ Copy score.daily and score.outcome to app schema in data/serving.duckdb
```

## Schema Definitions

### 1. `score.daily`
- `cik`: VARCHAR (10 digits)
- `as_of`: DATE (trading day of forecast)
- `question`: VARCHAR (`results_move`, `dilution`, `volatility`)
- `model_version`: VARCHAR (e.g. `lgbm_v1`, `xgb_v1`)
- `forecast_val`: DOUBLE (expected move, dilution prob, or expected vol)
- `band`: INTEGER (1 to 5)
- `coverage`: VARCHAR (`full`, `price_only`)
- `extra_json`: VARCHAR (JSON containing intervals `[vol_low, vol_high]` or probabilities `[p5, p10, p20]`)
- `scored_at`: TIMESTAMP

Primary Key / Idempotency Key: `(cik, as_of, question, model_version)`

### 2. `score.outcome`
- `cik`: VARCHAR (10 digits)
- `as_of`: DATE (trading day when forecast was made)
- `question`: VARCHAR
- `model_version`: VARCHAR
- `window_end`: DATE (date when window closed)
- `forecast_val`: DOUBLE
- `forecast_band`: INTEGER
- `actual_val`: DOUBLE (realized move, dilution 0/1, or realized vol)
- `error`: DOUBLE (forecast_val - actual_val or absolute error)
- `is_hit`: BOOLEAN (whether outcome matched predicted direction / band / interval)
- `evaluated_at`: TIMESTAMP

