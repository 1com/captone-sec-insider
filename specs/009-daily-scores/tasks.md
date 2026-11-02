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
