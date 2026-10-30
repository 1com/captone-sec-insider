---
description: "Task list for feature 006: Results-day move model"
---

# Tasks: Results-day move model

**Input**: Design documents from `specs/006-results-move-model/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/model-contract.md](contracts/model-contract.md),
[quickstart.md](quickstart.md)

**Tests**: In Phase 1 (US1 & US2), the notebook is executed end to end under the 5 GB memory cap and
verified for determinism, zero leakage, and holdout dry-run readiness. In Phase 2 (US3, after the
researcher approves the executed notebook), unit tests are added in
`tests/unit/test_results_move_model.py`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1 (build & compare levels in notebook), US2 (calibration, bands & dry run in
  notebook), US3 (move approved model to `src/sentinel/models/` with tests & CLI)
- Heavy runs use the memory cap:
  `systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run …`

---

## Phase 1: Setup

- [X] T001 Create branch `006-results-move-model` and write spec-kit design documents in `specs/006-results-move-model/`

---

## Phase 2: User Story 1 — Build, compare and choose the model in the notebook (Priority: P1) 🎯 MVP

**Goal**: Fill sections 1–7 and 9 of `notebooks/006-results-move-model.ipynb` to load the data,
construct the purged 2019–2022 walk-forward folds, build and tune Levels 0–3, compare them with the
one-standard-error rule, run the EDA diagnostics (2012+ training start, < 5 day windows, 5-seed
insider/macro ablations), log runs to MLflow, and inspect feature importance/coefficients.

**Independent Test**: Execute `notebooks/006-results-move-model.ipynb` under the 5 GB memory cap;
sections 1–7 and 9 complete without error and print the walk-forward comparison table.

- [ ] T002 [US1] Implement Section 1 (Setup and data) and Section 2 (Walk-forward folds with purge on `close_after`) in `notebooks/006-results-move-model.ipynb`
- [ ] T003 [US1] Implement Section 3 (Level 0 naive baseline `prev4_mean` and constant median floor) and Section 4 (Level 1 shrunk company history + volatility rule) in `notebooks/006-results-move-model.ipynb`
- [ ] T004 [US1] Implement Section 5 (Level 2 classic `Ridge` model on log-move with redundant-pair pruning, 1st/99th percentile clipping, median imputation + missing flags, standardisation) in `notebooks/006-results-move-model.ipynb`
- [ ] T005 [US1] Implement Section 6 (Level 3 `LightGBM` model on log-move with inner time-ordered validation and 2012+ training start check) in `notebooks/006-results-move-model.ipynb`
- [ ] T006 [US1] Implement Section 7 (Comparison table across 2019–2022, 1-SE selection rule, < 5 day window check, 5-seed insider & macro family ablations, MLflow logging) and Section 9 (What the model uses: feature importance and Ridge coefficients) in `notebooks/006-results-move-model.ipynb`

---

## Phase 3: User Story 2 — Calibrated chances, five risk bands, dry run and Findings (Priority: P1)

**Goal**: Fill sections 8 and 10 of `notebooks/006-results-move-model.ipynb`: calibrate `p_move_5`,
`p_move_10`, `p_move_20` on training data, evaluate Brier score, log loss and reliability across
2019–2022, build the 5 risk bands with historical median, interquartile range and hit rates, run the
holdout-readiness dry run on `latest.parquet` and 2023+ `feature_snapshot.parquet`, execute the full
notebook under the 5 GB cap, and write Section 10 (Findings) with the real numbers for the
researcher's review.

**Independent Test**: Execute `notebooks/006-results-move-model.ipynb` twice under the 5 GB memory
cap; predictions are identical, all band hit rates increase monotonically from Band 1 to Band 5, the
dry run produces 0 unexpected NaNs on eligible rows, and Section 10 summarises every result in plain
words.

- [ ] T007 [US2] Implement Section 8 (Isotonic probability calibration for >5%, >10%, >20% moves, 5 risk bands with hit rates, reliability plots, and holdout-readiness dry run on `latest.parquet` and 2023+ `feature_snapshot.parquet`) in `notebooks/006-results-move-model.ipynb`
- [ ] T008 [US2] Execute `notebooks/006-results-move-model.ipynb` start to finish under the 5 GB memory cap (`systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace notebooks/006-results-move-model.ipynb`) and verify determinism on a second run
- [ ] T009 [US2] Write Section 10 (Findings) in `notebooks/006-results-move-model.ipynb` quoting the executed aggregate results in plain English, re-execute, and present the summary to the researcher for approval

**Checkpoint (Researcher Approval Gate)**: Stop and show the researcher the executed notebook and
plain-English summary (`AGENTS.md` Step 5.3). Proceed to Phase 4 only after the researcher approves
the model.

---

## Phase 4: User Story 3 — Move approved model into `src/sentinel/models/` (Priority: P2, after approval)

**Goal**: Move the approved model into `src/sentinel/models/results_move.py` with unit tests and CLI
integration, and update `notebooks/006-results-move-model.ipynb` to import the package code and
reproduce identical numbers.

**Independent Test**: `uv run pytest -q`, `uv run ruff check src tests`, and re-executing
`notebooks/006-results-move-model.ipynb` all pass with identical walk-forward and band numbers.

- [ ] T010 [P] [US3] Write unit tests in `tests/unit/test_results_move_model.py` (point-in-time preprocessing, `fit` and `predict` determinism, probability monotonicity `p_move_5 >= p_move_10 >= p_move_20`, 5-band assignment, and dry-run scoring when `prev4_mean`/`n_prev` are absent from input columns)
- [ ] T011 [US3] Implement `src/sentinel/models/__init__.py` and `src/sentinel/models/results_move.py` (`ResultsMoveModel`, `fit`, `predict`, `evaluate_walk_forward`, MLflow logging) and wire the CLI command in `src/sentinel/cli.py`
- [ ] T012 [US3] Update `notebooks/006-results-move-model.ipynb` to import `sentinel.models.results_move`, re-execute under the 5 GB memory cap, and verify identical numbers

---

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T013 Update `docs/plan.md`, `README.md` and `AGENTS.md` status for 006, run `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest -q`, verify no notebook outputs are staged, and ask the researcher before merging `006-results-move-model` into `main`
