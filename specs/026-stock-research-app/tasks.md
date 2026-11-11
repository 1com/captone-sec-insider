---

description: "Task list for feature 026, the stock research app"
---

# Tasks: Stock research app, dilution first

**Input**: [spec.md](spec.md), [plan.md](plan.md). **Tests**: requested (FR-023, SC-004 to SC-007).
The researcher asked for a presentable MVP first (10 Nov); tasks after the MVP are marked "later".

## Phase 1: Setup

- [X] T001 Branch `026-stock-research-app`, the spec and its checklist; V2-61 in `docs/decisions.md`
- [X] T002 Lightweight Charts 4.2.0 vendored in `src/sentinel/web/static/`; V2-62

## Phase 2: Foundational

- [X] T003 `src/sentinel/web/data.py`: read-only queries, one connection per request, `NoData`
- [X] T004 `src/sentinel/web/glossary.py`: every form type with 100+ filings and every 8-K item
  (`tests/unit/test_web_glossary.py`)
- [X] T005 `src/sentinel/web/forecast.py`: the frozen model's chance, band and reasons per company
- [X] T006 `sentinel web` in `src/sentinel/cli.py` on port 8100, checked free

## Phase 3: User Story 1 - Look up a stock and judge its dilution risk (P1)

- [X] T007 [US1] Search (ticker, name, former names; reused tickers listed first) and company facts
- [X] T008 [US1] The dilution panel: chance, band, the band's record per test year, reasons, or why absent

## Phase 4: User Story 2 - Price and volume history (P1)

- [X] T009 [US2] Split-adjusted price and volume chart, periods, legend, insider and offering markers

## Phase 5: User Story 3 - Insider patterns (P2)

- [X] T010 [US3] Monthly bought and sold chart, pre-planned sales hidden on demand, the trade table
- [ ] T011 [US3] Clusters highlighted (later)

## Phase 6: User Story 4 - Filings in plain English (P2)

- [X] T012 [US4] Filings list with names, explanations, 8-K items, kind tabs, links

## Phase 7: User Stories 5-7

- [X] T013 [US5] Short-sale share of volume (FINRA), explained
- [ ] T014 [US5] Short interest as a new source (later; researcher, 10 Nov: built last)
- [ ] T015 [US6] Key financials as first filed (later)
- [X] T016 [US7] Diagnostics: the data behind the page and the dilution model's workings

## Phase 8: Polish

- [X] T017 Tests: `tests/unit/test_web_app.py` (search, facts, split adjustment, insider totals,
  filings, no volatility or results-day forecast, missing serving copy)
- [ ] T018 Daily forecasts in the daily update (009, dilution only) instead of the app (later)
- [ ] T019 Ten named cases checked against the data (SC-002, SC-005) (later)
- [X] T020 Docs (README, `docs/plan.md`, AGENTS.md); pull request after the researcher agrees (the
  MVP merged by #101, 10 Nov; the shared password, V2-63 and the docs by a second pull request,
  11 Nov)
- [ ] T021 Remove the old app (011-017) once the researcher approves the new one (FR-024)
