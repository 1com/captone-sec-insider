# Feature Specification: Daily scores and live outcomes

**Feature Branch**: `009-daily-scores`

**Created**: 2026-11-02

**Status**: Dilution forecasts in use since 12 Nov 2026 (V2-72); see the note below

> **Amended 12 Nov 2026 (decision V2-72; feature 026, T018).** Gemini's version of 2 Nov scored
> all three questions with files from `data/models/` that the researcher never approved; it stayed
> paused (V2-42). It was redone: the update now makes the **dilution forecasts only** (the app shows
> no volatility or results-day forecast, V2-61) with the **frozen approved object the holdout test
> scored** (V2-59, loaded from MLflow, never from `data/models/`), stores every input's value and
> contribution with each forecast, registers the model as `approved` in `model.registry`, and
> publishes approved models' forecasts only. Outcomes wait for the first windows to close (May
> 2027). Where the text below disagrees, this note wins.

**Input**: User description: "Step 6: implement daily scores and live outcomes (feature 009, issue #74)."

## Context

EDGAR-SENTINEL v2 answers three core forecasting questions for any US-traded stock:
1. **Expected Volatility** over the next 3 months (63 trading days).
2. **Expected Results-Day Move** on the next quarterly (10-Q) or annual (10-K) earnings release.
3. **Dilution Risk** (chance of share count increasing by 10%+ within 6 months).

In Feature 005, 006, and 007, the models were trained, evaluated, and packaged into `src/sentinel/models/`. 
Now, these models must be connected directly to the automated daily pipeline (`sentinel update`).

Every weekday at 10:00 AM, `sentinel update` refreshes SEC filings and market prices, computes the daily features in `data/exports/latest.parquet`, and updates `data/sentinel.duckdb`. Feature 009 adds:
1. **`score.daily`**: Generating forecasts for every covered stock on each trading day, mapping to 5 risk bands, and appending the records idempotently into `score.daily`.
2. **`score.outcome`**: Checking past forecasts whose time windows have closed, recording the true real-world outcome, and calculating the live hit rates.
3. **Serving integration**: Publishing `score.daily` and `score.outcome` into `data/serving.duckdb` under schema `app` so the web application and API (012–017) can display live forecasts and track records.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Daily Model Scoring inside `sentinel update` (Priority: P1)

When the daily update runs on a weekday, it loads today's feature snapshot (`latest.parquet`), executes the three frozen models (`results_move`, `dilution`, `volatility`), and appends the daily scores into `score.daily` in `data/sentinel.duckdb`.

**Why this priority**: Without daily scoring, the platform only has static historical backtests; scoring live active stocks is the core product requirement.

**Independent Test**: Run `sentinel update --no-fetch` on an existing database; `score.daily` is populated with forecasts for all covered active stocks across the three questions with 0 missing predictions on eligible rows. A second run on the same day detects no new date and inserts 0 duplicate rows (`nothing_new`).

**Acceptance Scenarios**:
1. **Given** `data/exports/latest.parquet` with active covered stocks, **When** daily scoring runs, **Then** forecasts are generated for each eligible stock:
   - `results_move`: predicted move, 5 risk bands, calibrated chances for >5%, >10%, >20% moves.
   - `dilution`: predicted dilution probability, 5 risk bands (Band 1: Very Low to Band 5: Imminent).
   - `volatility`: annualized volatility point forecast, 80% prediction interval (`vol_low_80`, `vol_high_80`).
2. **Given** an existing `score.daily` table, **When** daily scoring is re-run for a day that has already been scored, **Then** existing `(cik, as_of, question)` records are not duplicated (idempotence).
3. **Given** `price_only` stocks (stocks without SEC fundamental filings), **When** scoring runs, **Then** they receive volatility forecasts with coverage marked as `price_only`, and are excluded from dilution and results-day moves.

---

### User Story 2 - Outcome Tracking for Closed Windows (Priority: P1)

When a forecast's evaluation window closes in real life, `sentinel update` evaluates the outcome and records it into `score.outcome`:
- **Results-day move**: As soon as the post-earnings filing date (`close_after`) closes, the actual market-adjusted move is recorded.
- **Expected volatility**: After 63 trading days, the realized 63-day future volatility is recorded, along with whether it fell within the predicted 80% interval.
- **Dilution**: After 6 calendar months (or upon filing a qualifying dilutive report), whether shares outstanding increased by 10%+ is recorded.

**Why this priority**: The forecast contract and constitution require transparent live hit rates so users can verify the model's ongoing real-world accuracy.

**Independent Test**: Trigger outcome evaluation on historical development rows; `score.outcome` matches the pre-registered label answers in `label.results_move`, `label.dilution`, and `label.volatility` with 100% consistency.

**Acceptance Scenarios**:
1. **Given** closed forecasts in `score.daily`, **When** outcome tracking runs, **Then** `score.outcome` records the actual outcome, absolute error, and binary hit indicator.
2. **Given** open forecasts whose windows have not yet elapsed, **When** outcome tracking runs, **Then** they remain pending without errors.

---

### User Story 3 - Publication to Serving Database (`sentinel publish`) (Priority: P2)

When `sentinel publish` is invoked, it copies `score.daily` and `score.outcome` into `data/serving.duckdb` under schema `app` (`app.daily_score` and `app.live_outcomes`), ready for the web API and UI.

**Why this priority**: The web app (012–017) reads strictly from `data/serving.duckdb` in read-only mode.

**Independent Test**: Run `sentinel publish`; query `data/serving.duckdb` to verify that `app.daily_score` and `app.live_outcomes` exist and match the build database.

**Acceptance Scenarios**:
1. **Given** updated tables in `sentinel.duckdb`, **When** `sentinel publish` runs, **Then** `serving.duckdb` is atomically replaced or updated with fresh tables.
2. **Given** `sentinel verify`, **When** executed, **Then** all tables match identically.

