---

description: "Task list for feature 010, the holdout test"
---

# Tasks: The holdout test

**Input**: Design documents from `/specs/010-holdout-test/`

**Tests**: requested by the spec (FR-011).

## Phase 1: Setup

- [X] T001 Keep the export of 9 November in `data/frozen/2026-11-09/ml/` before the 10:00 update of 10 November; check each file's hash against its frozen model's data hash (research R1)

## Phase 2: Foundational

- [ ] T002 `eda.load(name, columns, folder=None)` in `src/sentinel/eda.py`: read a kept export
- [ ] T003 `validation.split_dilution(con, rows=None)` in `src/sentinel/validation.py`: the split-like rule on given answers (default: the development label table, as before)

## Phase 3: User Story 2 - The guard and the frozen levels (Priority: P1)

- [ ] T004 [US2] `src/sentinel/models/levels.py`: the simpler levels moved unchanged from the notebooks (dilution: base rate, offering rule, logistic regression with its Platt calibration; results move: base rates, baseline, rule, ridge with their three calibrations; volatility: baseline, rule, ridge with their 80% ranges on the out-of-sample history from 2014); for each question a walk-forward function for given years and a fit for one target year
- [ ] T005 [US2] `sentinel holdout --freeze-levels` in `src/sentinel/holdout.py` and `src/sentinel/cli.py`: check the kept export's hashes; re-run every simpler level on the test years and require every measure to equal the 008 record to 1e-9; make the levels for 2023; record them in MLflow (run `frozen-levels`, one artifact, tags with the data hash and the check)
- [ ] T006 [US2] `sentinel holdout --check`: the frozen models (V2-59), the frozen levels (V2-60), the registration lock, no earlier run; the 2023+ feature rows per question; no answer computed
- [ ] T007 [US2] Run `--freeze-levels` once on the kept export (under the memory cap, after the daily update); then `--check`

## Phase 4: User Story 1 - The one holdout test (Priority: P1)

- [ ] T008 [US1] `sentinel holdout --run` in `src/sentinel/holdout.py`: the guard; the 2023+ answers in memory (research R3); the rows; every level and the chosen model scored per calendar year and over all (research R5); the chosen model's bands; the records (008 contract) and the log entry; a printed summary

## Phase 5: User Story 3 - The same rule for the answers (Priority: P2)

- [ ] T009 [US3] Test in `tests/unit/test_holdout.py`: the label functions with a later end date give the development answers for every row whose window ended by 2022

## Phase 6: Polish

- [ ] T010 [P] Tests in `tests/unit/test_holdout.py`: the guard refuses (missing frozen model or levels, changed parameters, an earlier record or log); `--check` computes no answer; a synthetic run writes records the report shows
- [ ] T011 Quickstart for 16 November (`specs/010-holdout-test/quickstart.md`); README; `docs/plan.md`, `AGENTS.md`; ruff, format, tests; pull request after the researcher agrees (the test itself is run by the researcher on 16 November, after the merge)
