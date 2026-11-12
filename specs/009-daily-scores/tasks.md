---
description: "Task list for feature 009: Daily scores and live outcomes"
---

# Tasks: Daily scores and live outcomes

**Input**: Design documents from `specs/009-daily-scores/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md)

**Tests**: Unit tests in `tests/unit/test_daily_scores.py`, full test suite `uv run pytest -q`, and pipeline verification `sentinel verify`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files)
- **[Story]**: US1 (daily scoring), US2 (outcomes tracking), US3 (pipeline & serving)

---

## Phase 1: Setup & Contracts

- [X] T001 Define score and outcome contract in `specs/009-daily-scores/contracts/score-contract.md`

---

## Phase 2: User Story 1 — Daily Model Scoring (`score.daily`) (Priority: P1) 🎯 MVP

- [X] T002 [US1] Implement table creation for `score.daily` and `model.registry` in `src/sentinel/scoring/schema.py`
- [X] T003 [US1] Implement daily scoring logic in `src/sentinel/scoring/daily.py` (evaluating active stocks across `results_move`, `dilution`, `volatility`, mapping to 5 bands, handling `price_only` coverage, ensuring idempotence on re-runs)

---

## Phase 3: User Story 2 — Live Outcomes Recording (`score.outcome`) (Priority: P1)

- [X] T004 [US2] Implement outcome calculation in `src/sentinel/scoring/outcomes.py` (checking past forecasts with closed windows, computing realized actuals, prediction intervals hits, and inserting into `score.outcome`)

---

## Phase 4: User Story 3 — Pipeline & Serving Integration (Priority: P2)

- [X] T005 [US3] Wire daily scoring and outcomes tracking into `src/sentinel/update/run.py`
- [X] T006 [US3] Publish `score.daily` and `score.outcome` to `data/serving.duckdb` in `src/sentinel/serving/publish.py`
- [X] T007 [P] [US3] Implement unit tests in `tests/unit/test_daily_scores.py` (schema validation, idempotency, edge cases, outcomes)

---

## Phase 5: Polish & Verification

- [X] T008 Run code checks (`ruff check`, `ruff format`), execute `uv run pytest -q`, and verify pipeline determinism

---

## Phase 6: Redone for the approved model (V2-72, 12 Nov 2026; feature 026 T018)

- [X] T009 `src/sentinel/scoring/daily.py`: dilution only, with the frozen approved model from
  MLflow (`holdout.frozen_models`, V2-59), never `data/models/`; every input's value and
  contribution in `extra_json`; the model registered as `approved` in `model.registry`
- [X] T010 `src/sentinel/serving/publish.py`: `app.daily_score` holds each company's newest
  forecast of the last week from approved models only (Gemini's rows of 2 and 4 Nov stay in the
  log, never served); always present, empty when there is none
- [X] T011 The app (026) reads the stored forecasts instead of computing them
  (`src/sentinel/web/forecast.py`); `update.score: true` in `config/sources.yaml`
- [X] T012 Tests (`tests/unit/test_daily_scores.py`, `test_serving.py`, `test_update.py`,
  `test_web_app.py`); on the data of 11 Nov: 4,095 forecasts in 8 s (1.1 GB), the app's dilution
  panel for all 6,922 current companies identical before and after, the 13 named cases pass
- [ ] T013 The first scheduled run with forecasts: its log, a same-day rerun `nothing_new`,
  `sentinel verify` identical
