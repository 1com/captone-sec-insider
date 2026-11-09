---

description: "Task list for feature 005, volatility model"
---

# Tasks: Volatility model

**Input**: Design documents from `/specs/005-volatility-model/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R10, design check), data-model.md,
contracts/model-contract.md, quickstart.md

**Tests**: no separate test suite before approval: the notebook asserts its own invariants
(plan.md, Testing). Unit tests come with the move to `src/sentinel/models/` (Phase 8).

**Organization**: grouped by user story. Almost every task edits the one notebook
`notebooks/005-volatility-model.ipynb`, so tasks run in order; [P] marks the few that touch other
files. The notebook takes the shape of the approved 006 notebook; its present cells (headings and
instructions) are rewritten.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different file, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md

---

## Phase 1: Setup

- [X] T001 [P] Check the export (`data/exports/ml/volatility.parquet`, `latest.parquet`, `feature_snapshot.parquet`), nbstripout and that no heavy job holds the machine
- [X] T002 Rewrite the instruction cells of `notebooks/005-volatility-model.ipynb`: title (the question, the answer `vol_63_future`, the level, the 80% range and the bands, the baseline, the deciding measure V2-56, status); "What the answer means (read this first)" with a worked example; the rules (features per FR-002; folds by `eda.folds`; `Dated`, V2-49; V2-50; the range on all earlier years, V2-10); the holdout cell; the EDA's findings for this model

---

## Phase 2: Foundational (blocks every story)

- [X] T003 Section 1 of `notebooks/005-volatility-model.ipynb`: imports, `SEED = 0`, `THREADS = 8`; `eda.load("volatility")`, keep `eligible_volatility` true and the answer above 0 (the 93 zero answers left out), sort by `cik`, `as_of`; `FEATURES` = `eda.features(rows)` (95) with an assert that no answer, date, identifier, flag, `sector` or `cum_split_after` is in it; `log_vol`, `log_past` = log of the answer and of `vol_63`; print rows, companies, price-only rows and the answer's spread per year; MLflow experiment `005-volatility` (`005-volatility-trial` with `SENTINEL_TRIAL=1`) with tags from `dilution.provenance`
- [X] T004 Section 2 of `notebooks/005-volatility-model.ipynb`: `FOLDS = eda.folds(rows, "volatility", 2014..2022)` checked by `eda.check_folds`; fold table; assert train / purged / test counts equal `eda.purge_table(rows, "window_end", 2014..2022)`; helpers `valid_start(Y)`, `test_start(Y)`, `scores(mask, forecast, low, high)` (mean absolute log error, deciding; root mean squared log error; rank correlation; the range's coverage; the same for price-only stocks and US filers), `history_range(level, year)` (the 10th and 90th percentiles of the out-of-sample errors of every earlier year from 2014 whose answers were known before `year`, a `Dated` with cutoff `test_start(year)`), `history_bands(level, year)` (quintile edges of the same forecasts, a `Dated`), `run(level, year, fit)` (forecast the test year, keep the out-of-sample errors for later years, and for 2019–2022 score and log one MLflow run), `fit_level(make, features, f, year, grid, change)` (learn from inner rows the log or its change from `log_past`, choose the setting by the validation year's mean absolute log error)

**Checkpoint**: data, folds and helpers ready.

---

## Phase 3: User Story 1 - Compare the four levels and choose one (Priority: P1) 🎯 MVP

**Goal**: every level × test year scored; the simplest level within one standard error of the
yearly gaps chosen (V2-50).

**Independent Test**: run the notebook through section 7: it ends with the comparison tables and a
named choice.

- [X] T005 [US1] Section 3 of `notebooks/005-volatility-model.ipynb`: level 0 `baseline` (forecast `log(vol_63)`, a `Dated` that learns nothing) run for every year 2014–2022
- [X] T006 [US1] Section 4 of `notebooks/005-volatility-model.ipynb`: level 1 `rule`, `a + b · log(vol_63)` by least squares on inner rows; the slope per fold shown (below 1, H-V1)
- [X] T007 [US1] Section 5 of `notebooks/005-volatility-model.ipynb`: level 2 `ridge` on the change (research R3): logs of the volatilities; one of each |Spearman| ≥ 0.9 pair from `eda.redundant_pairs` on the 2019 fold's inner rows, fixed for every fold (keep the log versions and key features); cut at the 1st/99th training percentiles; median fill plus "was missing" indicators; standardise; `Ridge(alpha)`, alpha in {1, 10, 100, 1000} by the validation year
- [X] T008 [US1] Section 6 of `notebooks/005-volatility-model.ipynb`: level 3 `lightgbm` on the change: a `BoostRegressor` (squared-error loss, learning rate 0.05, feature and row fraction 0.8, `deterministic=True`, 8 threads, `random_state=SEED`) forecasting with its first `trees_` trees; grid `num_leaves` {15, 63} × `min_child_samples` {100, 500}, one fit of 1,000 trees each, trees from {50, 100, 150, 200, 300, 400, 600, 800, 1000} by the validation year; no early stopping (V2-49)
- [X] T009 [US1] Section 7 of `notebooks/005-volatility-model.ipynb`: tables level × test year for every measure, price-only stocks and US filers apart; the year-by-year one-standard-error choice on the mean absolute log error (V2-50), gaps and standard errors, the textbook choice for reference; whether the choice beats the baseline (SC-004) and the rule in every test year

**Checkpoint**: MVP: the choice can be read and judged.

---

## Phase 4: User Story 2 - A level, an honest 80% range and five bands (Priority: P2)

**Goal**: the range's coverage per test year and five bands with their outcomes.

**Independent Test**: the coverage table, the band table and the charts of section 8 alone.

- [X] T010 [US2] Section 8 of `notebooks/005-volatility-model.ipynb`: the chosen level's range per test year (its two multipliers and the years they came from); coverage per test year, overall and for price-only stocks; a chart of forecast against real volatility in ten groups per test year
- [X] T011 [US2] Section 8 of `notebooks/005-volatility-model.ipynb`: five bands with edges from the earlier years' forecasts; per band × test year: rows, median forecast, median real volatility, coverage; check that the median real volatility rises from band 1 to 5 in every year (reported, SC-006)

---

## Phase 5: User Story 3 - Understand what the model uses and judge the hypotheses (Priority: P3)

**Goal**: importance, leak check, a verdict per hypothesis.

**Independent Test**: the tables of sections 9 and 9b alone.

- [X] T012 [US3] Section 9 of `notebooks/005-volatility-model.ipynb`: the 2021 fold's top-20 LightGBM gain and top-20 ridge standardised coefficients; leak check: inputs ⊆ `FEATURES`; no single feature's rank correlation with the answer above 0.95 in size on the training rows
- [X] T013 [US3] Section 9b of `notebooks/005-volatility-model.ipynb`: hypotheses H-V1 to H-V6 (`docs/hypotheses.md`): family checks on the chosen level (LightGBM if `baseline` or `rule` is chosen), seeds 0–4 (one for the ridge), every fold, the fold's settings; direction checks with `eda.rank_by_year` on the test rows (`vol_63` +, `log_market_cap` −, `loss_making` +, `spy_vol_63` +) and the rule's slope below 1; H-V6 from the level comparison; one verdict per hypothesis; logged to MLflow

---

## Phase 6: User Story 4 - A model ready for the one holdout test (Priority: P4)

**Goal**: one frozen object, `predict(model, rows)`, dry run, determinism.

**Independent Test**: load the saved object and score the 2023+ month-end feature rows.

- [X] T014 [US4] Section 10 of `notebooks/005-volatility-model.ipynb`: `VolatilityModel`, `fit_frozen` and `predict(model, rows)` per contracts/model-contract.md: "a missing column is an error"; one row per input row (same index) with `eligible` and, for eligible rows, `vol_forecast`, `vol_low_80` and `vol_high_80` ("`vol_low_80 < vol_forecast < vol_high_80`"), `vol_band` (1–5) and `vol_band_name`
- [X] T015 [US4] Section 10 of `notebooks/005-volatility-model.ipynb`: fit the chosen level for target year 2023 (inner: answers known before 2022; settings from 2022; range and bands from the history 2014–2022) twice; assert identical predictions (SC-002); save with joblib and log as an MLflow artifact; show that it refuses a 2021 row
- [X] T016 [US4] Section 10 of `notebooks/005-volatility-model.ipynb`: dry run on the eligible month-end rows of `feature_snapshot.parquet` dated 2023 or later and the eligible rows of `latest.parquet` of companies still trading; assert one forecast per eligible row, low below level below high, bands 1–5; print the band counts (SC-007)

---

## Phase 7: Polish

- [X] T017 Trial run with `SENTINEL_TRIAL=1`, then the full run under the memory cap (`systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace notebooks/005-volatility-model.ipynb`); note the run time; check quickstart.md items 1–9 (9 Nov: trial 143 s; first full run 1,112 s: LightGBM best in 2019–2021, worst in 2022, the rule chose the baseline)
- [ ] T018 Findings cell of `notebooks/005-volatility-model.ipynb` from the outputs (aggregates only): the chosen level and why, its skill per test year against the baseline and the rule, the range's coverage, the bands, the hypothesis verdicts, what moves to `src/sentinel/models/`, open questions; export date and data hash on top
- [ ] T019 [P] Tick tasks here; update `AGENTS.md` and `docs/plan.md`; commit the notebook (outputs stripped) and the specs; show the researcher the executed notebook by the evening of 11 November (SC-008, V2-48)

---

## Phase 7b: The researcher's answer after the first run (9 Nov, V2-57)

- [ ] T023 Section 1 of `notebooks/005-volatility-model.ipynb`: `MACRO` (the 16 macro features) and `MODEL_FEATURES` (the 79 others); the ridge (redundant pairs found among `MODEL_FEATURES`) and LightGBM learn from `MODEL_FEATURES`; section 9b checks H-V4 by adding macro back; the instruction and section cells say so (FR-020)
- [ ] T024 Re-run the notebook start to finish under the memory cap; findings (T018) from the re-run, saying that V2-57 was decided after seeing the test years; tick T018–T019; show the researcher

---

## Phase 8: After the researcher's approval (FR-019)

- [ ] T020 Move `VolatilityModel`, the fitting with its range history, `predict`, `save`, `load` into `src/sentinel/models/volatility.py` (replacing Gemini's module); `sentinel train volatility` in `src/sentinel/cli.py`; `src/sentinel/scoring/daily.py` uses the model's bands (still paused, V2-42); the notebook imports the module and gives the same numbers
- [ ] T021 [P] Unit tests in `tests/unit/test_models_volatility.py` (features exclude the non-features, `sector`, `cum_split_after`; low below level below high; ineligible rows get no forecast; a missing column raises; a row dated before a cutoff is refused; identical output on two runs); Gemini's volatility test in `tests/unit/test_models.py` replaced
- [ ] T022 Log the approval in `docs/decisions.md`; pull request into `main` after the researcher agrees; close issue #67

---

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T004) → US1 (T005–T009) → US2 (T010–T011) and US3
  (T012–T013), both need US1's choice → US4 (T014–T016) needs the choice → Polish (T017–T019) →
  approval → Phase 8 (T020–T022).

### Parallel opportunities

- T001 alongside T002; T019's docs alongside the final read-through; T021 alongside T020.

## Implementation Strategy

1. MVP = Phases 1–3: the comparison table and the choice.
2. Then the range and bands (US2), the explanation and hypotheses (US3), the frozen model (US4), a
   full run and the findings.
3. Show the executed notebook to the researcher by 11 November evening; only after approval Phase 8.
