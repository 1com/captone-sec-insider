---
description: "Task list for feature 011: Web application & API"
---

# Tasks: Web Application & API (Features 011–017)

**Input**: Design documents from `specs/011-app-design/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [contracts/app-contract.md](contracts/app-contract.md)

**Tests**: Unit and integration tests in `tests/unit/test_app_api.py`, manual server verification on port 8090 (moved from 8080, 10 Nov).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel
- **[Story]**: US1 (Search & Overview), US2 (Intelligence Panels), US3 (Charts, Filings & Financials), US4 (Screener & Insiders)

---

## Phase 1: Setup & API Layer (Priority: P1)

- [X] T001 Implement read-only DuckDB client and service queries in `src/sentinel/app/db.py`
- [X] T002 Implement REST API endpoints in `src/sentinel/app/api.py` (`/api/search`, `/api/stock/{ticker}`, `/api/prices/{ticker}`, `/api/screener`, `/api/insiders`, `/api/freshness`)
- [X] T003 Implement unit tests for all API endpoints in `tests/unit/test_app_api.py`

---

## Phase 2: User Story 1 & 2 — Web Views & Stock Research Terminal (Priority: P1) 🎯 MVP

- [X] T004 Implement base layout template with dark-terminal styling, live search bar, and navigation in `src/sentinel/app/templates/base.html`
- [X] T005 Implement stock research page in `src/sentinel/app/templates/stock.html` featuring:
  - Header ribbon with real-time price, market cap, and coverage badge
  - The 4 core intelligence panels (Volatility 005, Results Move 006, Dilution 007, Insider Sentiment)
  - Interactive price & volume chart (Chart.js)
  - Tabbed deep dives: Reported Financials, Insider Activity (Form 4), SEC Filings Timeline

---

## Phase 3: User Story 4 — Screeners, Insider Feed & Model Card (Priority: P2)

- [X] T006 Implement multi-factor market screener view in `src/sentinel/app/templates/screener.html`
- [X] T007 Implement market-wide insider feed in `src/sentinel/app/templates/insiders.html`
- [X] T008 Implement model card & validation view in `src/sentinel/app/templates/model_card.html`

---

## Phase 4: CLI & Polish

- [X] T009 Add `sentinel serve` CLI command (port 8090 since 10 Nov) in `src/sentinel/cli.py`
- [X] T010 Run code formatting (`ruff check`, `ruff format`) and test suite (`pytest -q`)
