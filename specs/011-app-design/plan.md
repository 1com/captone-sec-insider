# Implementation Plan: Web Application & API (Features 011–017)

**Branch**: `011-app-design` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

## Summary

Build a high-performance, dark-slate equity research web workstation powered by FastAPI and Jinja2 templates, reading `data/serving.duckdb` in read-only mode. Serves universal search, full stock deep-dives with the 4 intelligence panels, interactive price charts, SEC filing timelines, financial history, market screeners, and insider feeds on **port 8090** (8080 belongs to another project).

## Technical Context

- **Backend Framework**: FastAPI + Uvicorn (already in dependencies).
- **Frontend Stack**: Jinja2 HTML templates, Tailwind CSS (CDN), Chart.js (CDN) for fast, zero-build lightweight frontend.
- **Data Source**: `data/serving.duckdb` (DuckDB connection opened in read-only mode, schema `app`).
- **Server Port**: Port 8090, checked free in WSL and on Windows (8000 and 8080 belong to other
  projects; moved from 8080 on 10 Nov); `sentinel serve` refuses a busy or reserved port.
- **Performance Requirement**: All API endpoints and page renders respond in under 50ms.
- **Constraints**: Public pages never serve Tiingo raw prices or proprietary holdout labels.

## App Endpoints & Route Map

### 1. Web Views (`src/sentinel/app/views.py`):
- `GET /` -> Redirects to `/screener` or market overview dashboard.
- `GET /stock/{ticker_or_cik}` -> Comprehensive stock research workstation.
- `GET /screener` -> Multi-factor stock screening table with live filters.
- `GET /insiders` -> Market-wide insider buying feed.
- `GET /model-card` -> Model validation, baselines, and walk-forward metrics.

### 2. JSON API (`src/sentinel/app/api.py`):
- `GET /api/search?q={query}` -> Instant ticker/company autocomplete.
- `GET /api/stock/{ticker}` -> Full payload (company card, forecasts, prices, financials, filings, insider trades).
- `GET /api/prices/{ticker}` -> Daily price and volume history for charts.
- `GET /api/screener` -> Filtered screener results with pagination.
- `GET /api/insiders` -> Recent cluster buys and officer transactions.
- `GET /api/freshness` -> Dataset latest dates and coverage counts.

