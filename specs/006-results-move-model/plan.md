# Implementation Plan: Results-day move model

**Branch**: `006-results-move-model` | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-results-move-model/spec.md`

## Summary

Build, evaluate and calibrate the results-day move forecast model (feature 006) under the
pre-registered D60 framework (`config/risk_params.yaml` v5) and the workflow in `AGENTS.md`:
1. **First in `notebooks/006-results-move-model.ipynb`**: implement and run all ten sections end to
   end on the development rows (`as_of <= 2022-12-31`, `eligible == True`) of
   `data/exports/ml/results_move.parquet`. Evaluate the four levels (Level 0 naive baseline
   `prev4_mean`, Level 1 shrunk history + volatility rule, Level 2 Ridge regression on log-move with
   redundant features pruned and 1st/99th percentile clipping + median imputation + missing flags,
   Level 3 LightGBM on log-move tuned via time-ordered inner validation) on purged walk-forward test
   years 2019–2022. Select the simplest level within one standard error of the best, calibrate the
   probabilities of a move > 5%, > 10% and > 20%, build the five risk bands with their hit rates,
   run the inner diagnostics (2012+ training start, window length < 5 days, 5-seed family ablation
   for insider and macro features), log runs to MLflow, run the holdout-readiness dry run on
   `latest.parquet` and 2023+ `feature_snapshot.parquet`, and present the executed notebook to the
   researcher for approval.
2. **After researcher approval**: move the approved model's training, calibration, band table,
   MLflow logging and `predict(model, rows)` scoring into `src/sentinel/models/results_move.py`
   (and shared model utilities in `src/sentinel/models/`), add unit tests in
   `tests/unit/test_results_move_model.py`, wire the CLI command, and update the notebook to import
   the package code and verify identical numbers.

## Technical Context

**Language/Version**: Python 3.14 (uv-managed)

**Primary Dependencies**: pandas, numpy, scipy, scikit-learn (`Ridge`, `StandardScaler`,
`IsotonicRegression`), lightgbm (`LGBMRegressor`), mlflow, matplotlib, pyarrow (all already locked
in `uv.lock`)

**Storage**: reads `data/exports/ml/results_move.parquet` (and for the dry run `latest.parquet` and
`feature_snapshot.parquet`, features only); logs model runs and artefacts to `data/mlflow.db`
(SQLite backend in `data/`, git-ignored); never modifies `data/sentinel.duckdb` or `data/exports/`

**Testing**: `nbconvert --execute` for the notebook under the 5 GB memory cap; `pytest` unit tests
on synthetic frames for `src/sentinel/models/` after approval

**Target Platform**: WSL2 on Windows (10 GB RAM, 5 GB systemd scope cap)

**Project Type**: single Python package (`src/sentinel/`) + `notebooks/`

**Performance Goals**: full notebook execution (all 4 levels × 4 folds + 5-seed ablations +
calibration + dry run) in under 5 minutes within the 5 GB memory cap

**Constraints**:
- No look-ahead: every fold's preprocessing, shrinkage, feature scaling, hyperparameter selection,
  probability calibration and band thresholds are fitted strictly on training rows (`as_of < Y-01-01`
  and `close_after < Y-01-01`).
- Sealed holdout: never read `data/exports/reference/` or compute answers for 2023+.
- Determinism: rows sorted by `cik, as_of`; `SEED = 0` fixed everywhere.
- Privacy: notebook outputs stripped on commit (`nbstripout`); written Findings quote aggregates
  only.

**Scale/Scope**: 157,566 eligible development rows across 5,947 companies (2010–2022), ~99 input
features (`sentinel.eda.features` + `prev4_mean`, `n_prev`, `sector`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this feature complies | Before | After design |
|---|---|---|---|
| I. Point-in-time | Uses only features as of `as_of` (the close before the release); training folds purge any row with `close_after >= Y-01-01`; all clippers/imputers/calibrators fit on purged training rows only | PASS | PASS |
| II. Covers what trades | Trains and scores on `eligible` rows; foreign filers do not file 8-K item 2.02 and are naturally absent; first-time filers (`n_prev == 0`) get a clean fallback so no eligible company is dropped | PASS | PASS |
| III. Survivorship | Includes disappeared companies priced from Tiingo in development rows | PASS | PASS |
| IV. Honest evaluation | Strictly follows D60 and `config/risk_params.yaml` v5: 4 levels on purged walk-forward years 2019–2022, 1-SE selection rule, calibrated chances (5%, 10%, 20%), 5 bands with hit rates, 5-seed family ablations, sealed 2023+ holdout untouched | PASS | PASS |
| V. Reproducibility | Rows sorted by `(cik, as_of)`, fixed seeds (`SEED = 0`), logged in MLflow with git commit and export date, reproducible by one command | PASS | PASS |
| VI. Data use | No network calls; Tiingo-derived individual rows never quoted in markdown; notebook outputs stripped by `nbstripout` | PASS | PASS |
| VII. Simplicity | Uses existing locked libraries (`scikit-learn`, `lightgbm`, `mlflow`); no new dependencies | PASS | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/006-results-move-model/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── model-contract.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
notebooks/
└── 006-results-move-model.ipynb       # Phase 1 deliverable (for researcher approval)

src/sentinel/models/                   # Phase 2 deliverable (after researcher approves notebook)
├── __init__.py
└── results_move.py

tests/unit/
└── test_results_move_model.py         # Phase 2 unit tests on synthetic data
```

**Structure Decision**: Per `AGENTS.md` §3 and Step 5, all four levels are first built, run and
tuned inside `notebooks/006-results-move-model.ipynb` and shown to the researcher for approval.
Once approved, the model code moves into `src/sentinel/models/results_move.py` with unit tests, and
the notebook imports that module.

## Complexity Tracking

No constitution violations.
