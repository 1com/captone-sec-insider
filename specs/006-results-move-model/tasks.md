---

description: "Task list for feature 006, results-day move model (rewritten 9 Nov)"
---

# Tasks: Results-day move model

**Input**: Design documents from `/specs/006-results-move-model/`

**Prerequisites**: plan.md, spec.md (rewritten 9 Nov), research.md (R1–R12, design check),
data-model.md, contracts/model-contract.md, quickstart.md

**Tests**: no separate test suite before approval: the notebook asserts its own invariants
(plan.md, Testing). Unit tests come with the move to `src/sentinel/models/` (Phase 8). This list
replaces Gemini's of 30 Oct, whose notebook used the look-ahead input `cum_split_after`.

**Organization**: grouped by user story. Almost every task edits the one notebook
`notebooks/006-results-move-model.ipynb`, so tasks run in order; [P] marks the few that touch
other files. The notebook takes the shape of the approved 007 notebook (instructions, sections
1–10 and 9b); Gemini's cells are replaced.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different file, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

---

## Phase 1: Setup

- [X] T001 [P] Check the export (`data/exports/ml/results_move.parquet`, `latest.parquet`, `feature_snapshot.parquet`), nbstripout (`uv run nbstripout --status`) and that no heavy job holds the machine
- [X] T002 Rewrite the instruction cells of `notebooks/006-results-move-model.ipynb`: title (the question, the answer `move`, the three events 5%/10%/20%, the baseline `prev4_mean`, the deciding measure V2-41, status); "What the answer means (read this first)" with a worked example; the rules (features per FR-002, V2-54; folds by `eda.folds`; `Dated`, V2-49; V2-50); the holdout cell; the EDA's findings for this model. Drop Gemini's code cells

---

## Phase 2: Foundational (blocks every story)

- [X] T003 Section 1 in `notebooks/006-results-move-model.ipynb`: imports, `SEED = 0`, `THREADS = 8`; `eda.load("results_move")`, keep `eligible` true and `move` present, sort by `cik`, `as_of` (stable); print (do not assert) releases, companies, releases per year and the base rates above 5%, 10%, 20% (156,926 releases, 5,937 companies, 39.8% / 17.1% / 4.0% on the export of 9 Nov)
- [X] T004 Section 1 of `notebooks/006-results-move-model.ipynb`: `FEATURES` = `eda.features(rows)` minus `TIMING` (`days_since_results`, `days_to_next_results`, `months_since_report`; V2-54) plus `prev4_mean`, `n_prev`: 94; assert none of `move`, `close_after`, `filing_date`, `report_date`, `cik`, `as_of`, `sector`, `cum_split_after`, the flags or the timing features is in it; `FAMILY` map from `eda.family`, with `prev4_mean`, `n_prev` as "history"
- [X] T005 Section 1 of `notebooks/006-results-move-model.ipynb`: derived columns `log_move = log(max(move, 0.0001))`, `above_5`, `above_10`, `above_20` (move above 0.05, 0.10, 0.20), `long_window` (`filing_date − report_date` ≥ 5 days); MLflow: tracking `sqlite:///data/mlflow.db` (`config.paths().mlflow_db`), artifacts `data/mlartifacts/`, experiment `006-results-move`, tags from `dilution.provenance(export)` (git commit, export date, data hash)
- [X] T006 Section 2 of `notebooks/006-results-move-model.ipynb`: `FOLDS = eda.folds(rows, "results_move")`, displayed through `eda.check_folds`; `train` = inner | gap | valid; fold table; assert train / purged / test counts equal `eda.purge_table(rows, "close_after")`
- [X] T007 Section 2 of `notebooks/006-results-move-model.ipynb`: helpers: `valid_start(Y)`, `test_start(Y)`; `calibrate(score_valid, mask, year)` → three Platt `Dated` calibrators (`LogisticRegression(C=1e6)` on the score, target `above_X`, cutoff `test_start`, slope asserted positive); `chances(cals, score, mask)` returning `p_move_5`, `p_move_10`, `p_move_20` put in order (`p_move_10 ≤ p_move_5`, `p_move_20 ≤ p_move_10`) and the count of rows put in order; `scores(mask, ch, size)` → log loss per event and their mean (deciding), Brier per event, rank correlation of `p_move_10` with `move`, mean absolute error and mean absolute log error of `size`; `valid_loss(...)` (the validation year's mean log loss after Platt on that year, for choosing settings); `record(level, year, ...)` keeping results and logging one MLflow run

**Checkpoint**: data, folds and helpers ready.

---

## Phase 3: User Story 1 - Compare the four levels by their chances and choose one (Priority: P1) 🎯 MVP

**Goal**: every level × test year scored on the three chances; the simplest level within one
standard error of the yearly gaps chosen (V2-50).

**Independent Test**: run the notebook through section 7: it ends with the comparison tables and a
named choice.

- [X] T008 [US1] Section 3 of `notebooks/006-results-move-model.ipynb`: the constant base rates (shares above 5%, 10%, 20% of the releases known before each test year; a `Dated` with cutoff `test_start`) recorded as `base_rate` (the floor, not a level); level 0 `baseline`: score `log(prev4_mean)`, a company's first release the inner releases' median log move (`Dated`, cutoff `valid_start`); calibrated on the validation year; size `prev4_mean` (first releases: the inner median move); recorded per test year
- [X] T009 [US1] Section 4 of `notebooks/006-results-move-model.ipynb`: level 1 `rule` (research R5): history = `log(prev4_mean)` shrunk toward the inner releases' median log move by `m / (m + k)`, `m = min(n_prev, 4)`; score = `a + b·history + c·log(vol_63)` with `a, b, c` by least squares on inner releases (`vol_63` missing: the inner median); `k` in {1, 2, 4} by `valid_loss`; `Dated` cutoff `valid_start`; the weights shown per fold; recorded per test year
- [X] T010 [US1] Section 5 of `notebooks/006-results-move-model.ipynb`: level 2 `ridge`: a scikit-learn pipeline fitted on inner releases only: logs of `prev4_mean` and the volatilities (`vol_21`, `vol_63`, `vol_252`, `range_vol_21`, `idio_vol_252`); one of each |Spearman| ≥ 0.9 pair from `eda.redundant_pairs` on the 2019 fold's inner releases, fixed for every fold (keep the log versions); cut at the 1st/99th training percentiles; median fill plus "was missing" indicators; standardise; `Ridge(alpha)`, alpha in {1, 10, 100, 1000} by `valid_loss`; `Dated` cutoff `valid_start`; recorded per test year
- [X] T011 [US1] Section 6 of `notebooks/006-results-move-model.ipynb`: level 3 `lightgbm`: a `BoostRegressor` (LightGBM regression of `log_move`, learning rate 0.05, `colsample_bytree` 0.8, `subsample` 0.8 every iteration, `deterministic=True`, `force_row_wise=True`, 8 threads, `random_state=SEED`) forecasting with its first `trees_` trees; grid `num_leaves` {15, 63} × `min_child_samples` {100, 500}, one fit of 800 trees each, trees from {50, 100, 150, 200, 300, 400, 600, 800} by `valid_loss`; no early stopping (V2-49); `Dated` cutoff `valid_start`; the chosen setting per fold; recorded per test year
- [X] T012 [US1] Section 7 of `notebooks/006-results-move-model.ipynb`: tables level × test year for every measure; the year-by-year one-standard-error choice on the mean log loss (V2-50; order `baseline`, `rule`, `ridge`, `lightgbm`), the gaps per year and their standard errors, the textbook choice for reference; whether the choice beats the base rates (SC-004) and the rule in every test year (if not the rule: say so and recommend it, spec US1 scenario 4)

**Checkpoint**: MVP: the choice can be read and judged.

---

## Phase 4: User Story 2 - Honest chances in five bands (Priority: P2)

**Goal**: five bands by the chance above 10% with forecast and real shares per test year.

**Independent Test**: the band table and the calibration charts of section 8 alone.

- [X] T013 [US2] Section 8 of `notebooks/006-results-move-model.ipynb`: band edges at the quintiles of the chosen level's validation-year `p_move_10` per fold (`dilution.Bands` in a `Dated`, cutoff `test_start`, V2-53); per band × test year: releases, mean forecast and real share above 5%, 10% and 20%, median move; check that the real share above 10% and the median move rise from band 1 to 5 in every year (reported, SC-005)
- [X] T014 [US2] Section 8 of `notebooks/006-results-move-model.ipynb`: calibration charts per event and test year (forecast against real share in tenths of the forecast); the count of releases whose chances were put in order (SC-006: every release in order after it)

---

## Phase 5: User Story 3 - Understand what the model uses and judge the hypotheses (Priority: P3)

**Goal**: importance, leak check, D60's and the EDA's checks, a verdict per hypothesis.

**Independent Test**: the tables of sections 9 and 9b alone.

- [X] T015 [US3] Section 9 of `notebooks/006-results-move-model.ipynb`: the 2021 fold's top-20 LightGBM gain and top-20 ridge standardised coefficients; leak check: inputs ⊆ `FEATURES`; no single feature with AUC ≥ 0.95 or ≤ 0.05 for any event on the training releases
- [X] T016 [US3] Section 9 of `notebooks/006-results-move-model.ipynb`: the chosen level refitted from 2012 on every fold beside the 2010 fit (reported, research R8); its measures on the test years with and without the long windows (reported)
- [X] T017 [US3] Section 9b of `notebooks/006-results-move-model.ipynb`: the hypotheses H-R1 to H-R6 (`docs/hypotheses.md`): family checks on the chosen level (LightGBM if `baseline` or `rule` is chosen), seeds 0–4 (one for ridge), every fold, the fold's settings: refit without the family, the change of the mean log loss per test year, "adds" if its mean exceeds one standard error of the four yearly changes; families per research R10; direction checks with `eda.rank_by_year` on the test releases (`prev4_mean` +, `idio_vol_252` +, `log_market_cap` −, `loss_making` +, `vix` +; the expected sign in at least three of four years); one verdict per hypothesis (supported / not supported / opposite); logged to MLflow

---

## Phase 6: User Story 4 - A model ready for the one holdout test (Priority: P4)

**Goal**: one frozen object, `predict(model, rows)`, dry run, determinism.

**Independent Test**: load the saved object and score the 2023+ release-eve feature rows.

- [X] T018 [US4] Section 10 of `notebooks/006-results-move-model.ipynb`: `ResultsMoveModel`, `fit(rows, year, ...)` and `predict(model, rows)` per contracts/model-contract.md: "a missing column is an error"; output one row per input row (same index) with `eligible` and, for eligible rows, `p_move_5`, `p_move_10`, `p_move_20` ("floats in [0, 1], in order"), `move_band` (1–5) and `move_band_name`
- [X] T019 [US4] Section 10 of `notebooks/006-results-move-model.ipynb`: fit the chosen level for target year 2023 (inner: moves known before 2022; settings, calibrations and band edges from the releases of 2022) twice; assert identical predictions (SC-002); save with joblib and log as an MLflow artifact tagged `frozen=candidate`; show that it refuses a 2021 release
- [X] T020 [US4] Section 10 of `notebooks/006-results-move-model.ipynb`: dry run on the eligible release-eve rows of `feature_snapshot.parquet` dated 2023 or later (54,767; read with a date filter) and the eligible rows of `latest.parquet`, with `prev4_mean` and `n_prev` given as missing; assert one prediction per eligible row, chances in [0, 1] and in order, bands 1–5; print the band counts (SC-007)

---

## Phase 7: Polish

- [X] T021 Trial run with a small grid, then the full run under the memory cap (`systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace notebooks/006-results-move-model.ipynb`); note the run time; check quickstart.md items 1–9 (9 Nov: trial 77 s; full run 424 s, every check passed)
- [X] T022 Findings cell of `notebooks/006-results-move-model.ipynb` from the outputs (aggregates only): the chosen level and why, its skill per test year against the base rates, the baseline and the rule, the bands and their hit rates, the checks, the hypothesis verdicts, what moves to `src/sentinel/models/`, open questions; export date and data hash on top
- [ ] T023 [P] Tick tasks here; update `AGENTS.md` and `docs/plan.md`; commit the notebook (outputs stripped) and the specs; push the branch; show the researcher the executed notebook (SC-008)

---

## Phase 8: After the researcher's approval (FR-019)

- [X] T024 Move `ResultsMoveModel`, `fit`, `predict`, `save`, `load` into `src/sentinel/models/results_move.py` (replacing Gemini's module); `sentinel train results_move` in `src/sentinel/cli.py`; `src/sentinel/scoring/daily.py` reads the new output (`forecast_val` = `p_move_10`, the three chances and the band name in `extra_json`; still paused, V2-42); the notebook imports the module and gives the same numbers (9 Nov: re-run at `ad232a7`, every number identical; `sentinel train`/`score results_move` checked into a scratch folder)
- [X] T025 [P] Unit tests in `tests/unit/test_models_results_move.py` (features exclude the non-features, `sector`, `cum_split_after` and the timing features; chances in [0, 1] and in order; ineligible rows get no chance; a missing column raises; a row dated before a cutoff is refused; identical output on two runs); Gemini's results-move tests in `tests/unit/test_models.py` replaced
- [ ] T026 Log the approval in `docs/decisions.md`; pull request into `main` after the researcher agrees; close issue #77

---

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T007) → US1 (T008–T012) → US2 (T013–T014) and US3
  (T015–T017), both need US1's choice → US4 (T018–T020) needs the choice → Polish (T021–T023) →
  approval → Phase 8 (T024–T026).
- US2 and US3 are independent of each other but share the notebook, so they run one after the
  other.

### Parallel opportunities

- T001 alongside T002; T023's docs alongside the final read-through; T025 alongside T024.

## Implementation Strategy

1. MVP = Phases 1–3: the comparison table and the choice (the researcher can already judge
   whether a model beats the baseline and the rule).
2. Then bands (US2), explanation and hypotheses (US3), frozen model (US4), a full run and the
   findings.
3. Show the executed notebook to the researcher; only after approval Phase 8.
