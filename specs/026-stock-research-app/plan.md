# Implementation Plan: Stock research app, dilution first

**Branch**: `026-stock-research-app` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

## Summary

A new package `src/sentinel/web/` (separate from Gemini's `src/sentinel/app/`, which stays until the
researcher approves the new app): FastAPI serving one server-rendered page and small JSON endpoints,
read-only over the serving copy. The page is drawn by one plain JavaScript file with TradingView
Lightweight Charts 4.2.0 (vendored, Apache-2.0; V2-62). The dilution forecast comes from the frozen
approved model (V2-52, V2-59), loaded once from MLflow and applied to the latest feature rows
(`app.company_card`) of every eligible company still trading, again whenever a new serving copy is
published; its reasons are the trees' per-feature contributions. The SEC forms and 8-K items are
explained by a glossary module. `sentinel web` serves it on port 8100 (checked free in WSL and on
Windows), this machine only by default.

The researcher asked for a presentable MVP within the hour (10 Nov): the slower parts are listed
under "After the MVP" and in `tasks.md`.

## Technical Context

**Language/Version**: Python 3.14 (uv); JavaScript in the browser (no build step).
**Dependencies**: existing (FastAPI, Jinja2, DuckDB, pandas, LightGBM, MLflow); new: Lightweight
Charts 4.2.0, one vendored file in `src/sentinel/web/static/` (V2-62).
**Storage**: reads `data/serving.duckdb` (read-only, one connection per request, 2 GB cap), the
frozen model in MLflow (`data/mlflow.db`) and `docs/report/model_card.json` (bands, test years).
**Testing**: pytest on a small test copy of the serving tables; the glossary's coverage of every
form type with at least 100 filings and every 8-K item.
**Constraints**: no invented or typed-in value; no volatility or results-day forecast; this machine
only (Tiingo-derived prices are shown; FR-020: no public page); the port checked free.

## Constitution Check

| Principle | How this plan complies | Status |
|---|---|---|
| I Point-in-time | the forecast uses each company's latest feature row, built from facts known by that day | ✅ |
| IV Honest evaluation | the frozen approved model, unchanged; no 2023+ answer is computed or shown | ✅ |
| V Reproducibility | every number read from the serving copy or the model report's records | ✅ |
| VI Lawful data use | this machine only; Tiingo-derived prices never on a public page | ✅ |
| VII Simplicity | FastAPI with a server-rendered page; one vendored chart library, logged as V2-62 | ✅ |

## Project Structure

```text
src/sentinel/web/main.py        the app: the page and the JSON endpoints
src/sentinel/web/data.py        read-only queries of the serving copy; NoData when it is missing
src/sentinel/web/forecast.py    the frozen model's chances, bands and reasons for current companies
src/sentinel/web/glossary.py    plain-English names of SEC forms and 8-K items
src/sentinel/web/templates/     index.html (one page)
src/sentinel/web/static/        app.js, app.css, lightweight-charts.js (4.2.0)
src/sentinel/cli.py             `sentinel web` (port 8100, checked free)
tests/unit/test_web_app.py, tests/unit/test_web_glossary.py
```

## After the MVP

The daily forecasts moved into the daily update (009, dilution only, FR-005); insider clusters
highlighted (FR-008); key financials (User Story 6); short interest as a new source (researcher,
10 Nov: built last); a page-number test against the data for ten named cases (SC-002, SC-005);
removing the old app (FR-024, with the researcher's agreement).
