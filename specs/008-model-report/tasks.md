---

description: "Task list for feature 008, model report and model card data"
---

# Tasks: Model report and model card data

**Input**: Design documents from `/specs/008-model-report/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R7), data-model.md, contracts/, quickstart.md

**Tests**: requested by the spec (FR-010): `tests/unit/test_model_report.py` on a temporary MLflow
store.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [ ] T001 Read Gemini's `src/sentinel/models/report.py`, `tests/unit/test_model_report.py` and `docs/model_report.md`; list what is replaced (research R4)

## Phase 2: Foundational

- [ ] T002 `record(question, tables, tags)` in `src/sentinel/models/report.py`: one MLflow run named `report` with tags `report=true` and the notebook's tags, one artifact `report.json` per contracts/report-record.md (tables as columns and data, numbers as JSON numbers, missing values as null)
- [ ] T003 `load_records(tracking_uri)` in `src/sentinel/models/report.py`: per question the newest run named `report` with `report=true` and `trial=False` in its experiment, with its run id and tags; a missing question raises an error naming the notebook to run; the holdout records of experiment `010-holdout` when they exist

## Phase 3: User Story 1 - One command writes the model report (Priority: P1) 🎯 MVP

- [ ] T004 [US1] The recording cell at the end of `notebooks/007-dilution-model.ipynb` (before the findings): the tables of contracts/report-record.md from the notebook's variables, through `report.record`
- [ ] T005 [US1] The recording cell at the end of `notebooks/006-results-move-model.ipynb`
- [ ] T006 [US1] The recording cell at the end of `notebooks/005-volatility-model.ipynb`
- [ ] T007 [US1] `generate_report(paths, tracking_uri, out)` in `src/sentinel/models/report.py`: per question the sections of research R5 rendered from the record (Markdown tables by the module's own renderer), the figures (the deciding measure by level and year; the calibration or forecast-against-real chart), an opening summary of the three questions; no date in the files; `sentinel report` in `src/sentinel/cli.py` writes `docs/report/` and says where
- [ ] T008 [US1] Re-run the three notebooks one after the other on the same export under the memory cap (quickstart); 006 and 005 give their approved numbers (compare the outputs); 007's differences from its approved run of 5 Nov, if any, recorded
- [ ] T009 [US1] Run `sentinel report`; check one table per question against MLflow; run it twice and compare the files (SC-001, SC-002)

## Phase 4: User Story 2 - The model card data (Priority: P2)

- [ ] T010 [US2] `docs/report/model_card.json` written by `generate_report` per contracts/model-card.md (bands per test year and pooled)

## Phase 5: User Story 3 - The holdout section (Priority: P3)

- [ ] T011 [US3] The holdout section of each question and the model card's `holdout`: "not run yet" without a record of experiment `010-holdout`, the record's tables unedited with it

## Phase 6: Polish

- [ ] T012 [P] Tests in `tests/unit/test_model_report.py` (replacing Gemini's): synthetic records in a temporary store; the numbers equal the recorded ones; trial and older records ignored; a missing question stops the command; two runs identical; the holdout section with and without a record
- [ ] T013 Remove Gemini's `docs/model_report.md` and `docs/figures/`; generate and commit `docs/report/`; README and `docs/plan.md`, `AGENTS.md`; ruff, format, tests; pull request after the researcher agrees; close issue #79

## Dependencies

- T002–T003 → T004–T006 (the notebooks use `record`) → T007 → T008 (re-runs) → T009–T011 → T012 →
  T013.
