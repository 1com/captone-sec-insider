---

description: "Task list for feature 007, dilution model"
---

# Tasks: Dilution model

**Input**: Design documents from `/specs/007-dilution-model/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/frozen-model.md,
quickstart.md

**Tests**: no separate test suite before approval: the notebook asserts its own invariants
(plan.md, Testing). Unit tests come with the move to `src/sentinel/models/` (Phase 8).

**Organization**: grouped by user story. Almost every task edits the one notebook
`notebooks/007-dilution-model.ipynb`, so tasks run in order; [P] marks the few that touch other
files.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different file, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

---

## Phase 1: Setup

- [X] T001 Level-3 estimator decided (research R10): scikit-learn `HistGradientBoostingClassifier` for now, LightGBM after `brew install libomp` later; threads limited to 4
- [X] T002 [P] Check the export: `data/exports/ml/dilution.parquet`, `latest.parquet`, `feature_snapshot.parquet` present; nbstripout installed (`uv run nbstripout --status`)

---

## Phase 2: Foundational (blocks every story)

- [X] T003 Section 1 code cell in `notebooks/007-dilution-model.ipynb`: imports, `SEED = 0`, load `eda.load("dilution")`, keep `eligible_dilution` true and `dilution` present, sort by `cik`, `as_of`; assert 409,576 rows and base rate 9.59% (rounded); print rows and companies per year
- [X] T004 Section 1: feature list `FEATURES = eda.features(rows)` minus `cum_split_after` (95), assert none of `dilution`, `window_end`, `cik`, `as_of`, `cum_split_after`, flags or coverage columns is in it; family lists for macro, short volume, insider (from `eda.family`)
- [X] T005 Section 1: MLflow set-up in the same cell: tracking URI `sqlite:///data/mlflow.db` (from `config.paths().mlflow_db`), artifact root `data/mlartifacts/`, experiment `007-dilution`; tags `git_commit` (from `git rev-parse HEAD`), `export_date` (file date of `dilution.parquet`), `data_hash` (first 12 hex of its SHA-256)
- [X] T006 Section 2 code cell: `fold(Y)` returning train / inner-train / validation / test row masks per data-model.md ("train: `window_end` < 1 Jan Y; inner-train: `window_end` < 1 Jan Y−1; validation: `as_of` in Y−1; test: `as_of` in Y"); print the table and assert train/purged/test counts equal `eda.purge_table(rows, "window_end")`
- [X] T007 Section 2: shared helpers `scores(y, p)` (log loss, AUC via `eda.auc`, Brier, lift via `eda.top_decile_lift`) and `log_run(level, year, params, metrics)` to MLflow

**Checkpoint**: data, folds and helpers ready.

---

## Phase 3: User Story 1 - Compare the four levels and choose one (Priority: P1) 🎯 MVP

**Goal**: every level × test year scored; the simplest level within one SE of the best chosen.

**Independent Test**: run the notebook through section 7: it ends with the comparison table and
a named choice.

- [X] T008 [US1] Section 3: level 0, base rate from each fold's train rows; scores per test year; Brier near 0.0867
- [X] T009 [US1] Section 4: level 1, rule `n_offering_12m > 0` with the train rows' rate when flagged / not; scores per test year; assert AUC within 0.69–0.76; also show the shelf and share-growth rules for context (not as levels)
- [X] T010 [US1] Section 5: level 2, sklearn pipeline fitted on inner-train rows only: drop macro and short-volume families; drop one of each |Spearman| ≥ 0.9 pair from `eda.redundant_pairs` on the 2019 fold's train rows (keep `log_addv20`, `log_market_cap`, `log_close`); cut at 1st/99th training percentiles; median fill + "was missing" indicators; standardise; L2 logistic regression with C chosen from {0.01, 0.1, 1} by validation log loss
- [X] T011 [US1] Section 6: level 3, `HistGradientBoostingClassifier` (stand-in for LightGBM, R10) on all 95 features fitted on inner-train rows: learning rate 0.05, `max_features` 0.8, `random_state=0`, 4 threads; grid `max_leaf_nodes` {15, 63} × `min_samples_leaf` {100, 500} with early stopping (100 rounds, max 2,000 iterations) on the validation year via `X_val`/`y_val`
- [X] T012 [US1] Sections 5–6: Platt calibration (logistic fit on the model's log-odds) on the validation year for levels 2 and 3; score test years with raw and calibrated chances; log every level × year to MLflow
- [X] T013 [US1] Section 7: comparison table (level × year × measure), mean and SE per level; choose the simplest level with mean log loss ≤ best mean + best SE; print the reason; state whether it beats the rule in every year (SC-004) and note that 2022 is January–June only

**Checkpoint**: MVP: the choice can be read and judged.

---

## Phase 4: User Story 2 - Calibrated chances in five bands (Priority: P2)

**Goal**: five bands with forecast and real dilution rate per test year.

**Independent Test**: the band table and calibration chart from section 8 alone.

- [X] T014 [US2] Section 8: band edges at the quintiles of the chosen level's calibrated validation-year chances per fold; table of rows, mean forecast and real rate per band × test year; assert the real rate rises from band 1 to 5 in every year (report, do not fail, if not)
- [X] T015 [US2] Section 8: calibration chart (forecast vs real rate in ten groups) per test year with matplotlib

---

## Phase 5: User Story 3 - Understand what the model uses (Priority: P3)

**Goal**: importance, leak check and the insider/macro family check.

**Independent Test**: section 9's tables alone.

- [X] T016 [US3] Section 9: top-20 importance (LightGBM gain) and top-20 standardised coefficients (logistic); leak check: inputs ⊆ `FEATURES`, no single feature with AUC ≥ 0.95 or ≤ 0.05 on train rows
- [X] T017 [US3] Section 9: family check: refit LightGBM (chosen settings) without insider, and without macro, seeds 0–4, every fold; table of mean log-loss change vs the full model with its spread; log to MLflow

---

## Phase 6: User Story 4 - A model ready for the one holdout test (Priority: P4)

**Goal**: one frozen object, `predict(model, rows)`, dry run, determinism.

**Independent Test**: load the saved object and score the 2023+ feature rows.

- [X] T018 [US4] Section 10 code: `DilutionModel` and `predict(model, rows) -> DataFrame[cik, as_of, chance, band]` per contracts/frozen-model.md ("one row per input row with `model.eligibility` true"; "a missing feature column is an error")
- [X] T019 [US4] Section 10: refit the chosen level for target year 2023 (inner-train `window_end` < 2022-01-01, calibration and band edges from 2022 rows); twice; assert identical predictions; save with joblib and log as MLflow artifact tagged `frozen=candidate`
- [X] T020 [US4] Section 10: dry run: score `latest.parquet` and the `feature_snapshot.parquet` rows dated after 2022 (features only, read with a date filter); assert one chance per eligible row, all in [0, 1], no missing; band counts printed

---

## Phase 7: Polish

- [X] T021 Section 10 markdown: findings in plain words (chosen level and why, skill per year vs base rate and rule, bands, what moves to `src/sentinel/models/`, open questions); update the title cell (status, Brier 0.0867)
- [X] T022 Run the notebook start to finish with `uv run jupyter nbconvert --to notebook --execute --inplace notebooks/007-dilution-model.ipynb`; check quickstart.md items 1–7
- [X] T023 [P] Update `PROJEKT_STATUS.md` (local) and tick tasks here; commit the notebook (outputs stripped) and specs; push branch `007-dilution-model`

---

## Phase 8: After the researcher's approval (not part of the notebook work)

- [ ] T024 Move `DilutionModel`, fitting and `predict` into `src/sentinel/models/dilution.py`; the notebook imports them and gives the same numbers
- [ ] T025 [P] Unit tests in `tests/unit/test_models_dilution.py`: feature list excludes non-features and `cum_split_after`; predict skips ineligible rows; deterministic output; missing feature column raises
- [ ] T026 Pull request into `main` after the researcher agrees; close issue #78

---

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T007) → US1 (T008–T013) → US2 (T014–T015) and US3
  (T016–T017), both need US1's choice → US4 (T018–T020) needs the choice → Polish → Phase 8.
- US2 and US3 are independent of each other but share the notebook, so they run one after the
  other.

### Parallel opportunities

- T002 alongside T001; T023 alongside the final read-through; T025 alongside T024.

## Implementation Strategy

1. MVP = Phases 1–3: the comparison table and the choice (the researcher can already judge
   whether a model beats the offering rule).
2. Then bands (US2), explanation (US3), frozen model (US4), findings and a full run.
3. Show the executed notebook to the researcher; only after approval Phase 8.
