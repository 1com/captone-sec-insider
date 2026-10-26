# Tasks: Training Data (Labels, Features, ML Dataset)

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md)

## Phase 1: Setup and the lock

- [X] T001 Create `src/sentinel/labels/`, `features/`, `ml/` packages and the `lab`, `feat`, `ml` schemas in `warehouse.SCHEMAS`.
- [X] T002 [P] Write `tests/unit/test_lock.py`: no tag → refused; tag with a different `params.yaml` → refused; matching tag → allowed. The guard sits in the CLI steps, so unit tests call the build functions on synthetic warehouses.
- [X] T003 Implement `src/sentinel/lock.py` (research R1) and exit code 7 in `cli.py`.

## Phase 2: User Story 1 — labels (P1)

- [X] T004 [P] [US1] `tests/unit/test_labels.py`: BHAR against SPY, IWM, EW and VW industry on synthetic paths; FF6 CAR with known betas and no intercept; entry at close when the open is unusable; delisting for each class with bounds; the 31 December 2022 boundary per horizon; net = gross − cost and null cost; unmapped SIC → "Other"; purchase outcomes and their boundary.
- [X] T005 [US1] Implement `labels/returns.py` and `labels/build.py`; `sentinel labels`.

## Phase 3: User Story 2 — features (P1)

- [X] T006 [P] [US2] `tests/unit/test_features.py`: F1–F29 on a synthetic issuer against hand values; XBRL first filed after T ignored; F10 window rule; F9 routine and opportunistic; truncation test (delete every record after T, rebuild, compare).
- [X] T007 [US2] Implement `features/build.py`; `sentinel features`.

## Phase 4: User Story 3 — the dataset (P1)

- [X] T008 [P] [US3] `tests/unit/test_ml_dataset.py`: fold membership, slices, purging, weights, fold-1 rule, dollar scaling, no window across its boundary or 31 December 2022, version row and Parquet files.
- [X] T009 [US3] Implement `ml/dataset.py`; `sentinel ml-dataset`.

## Phase 5: Registration, docs, real run

- [X] T010 Add the new tables to the Tiingo register and to `tests/integration/test_rebuild_identical.py`.
- [X] T011 Decision entry D53 (research R1–R12) in `docs/initialplan.md` §12 for the researcher's approval (task L.2).
- [ ] T012 After `prereg-v1`: real run of the three steps under the memory ceiling; counts, timings and peak memory in `run-notes.md`; post-floor counts and effective sample sizes per fold (SC-004); 10 labels for the researcher's hand check (SC-002).
- [ ] T013 `uv run pytest`, `ruff check`, `ruff format --check`; tick tasks; commit; merge after the researcher's approval.
