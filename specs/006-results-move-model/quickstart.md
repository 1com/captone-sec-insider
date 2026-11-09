# Quickstart: Results-day move model (006)

## Prerequisites

- The repository on branch `006-results-move-model`, `uv sync` done.
- The private export: `data/exports/ml/results_move.parquet`, `latest.parquet` and
  `feature_snapshot.parquet` (written by the daily update's `sentinel export`).
- nbstripout installed once: `uv run nbstripout --install --attributes .gitattributes`.
- No other heavy job running (the daily update runs at 10:00 on weekdays).

## Run

```bash
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace notebooks/006-results-move-model.ipynb
```

Expected: finishes without errors in about 20–30 minutes (007 took 17 minutes on 2.6 times as
many rows, with one model per fold; 006 fits one model per fold and level, and three calibrations).

## What to check (maps to the spec's success criteria)

1. **Section 1**: the learnable releases (156,926 releases, 5,937 companies on the export of
   9 Nov), the base rates (about 40%, 17% and 4% above 5%, 10% and 20%), the feature list with
   `prev4_mean` and `n_prev` and without `cum_split_after`.
2. **Section 2**: the fold table from `eda.check_folds` (inner, validation, left out, test per
   test year); counts equal `eda.purge_table` (the purge removes at most a few releases a year).
3. **Sections 3–7**: every level × test year with the log loss of each chance and their mean
   (deciding, V2-41), Brier scores beside the base rates', rank correlation, absolute and log
   errors; the yearly leads with their standard errors and the named choice (V2-50) (SC-003,
   SC-004).
4. **Section 8**: the five bands ordered by the chance above 10% (V2-53); per test year the real
   shares above 5%, 10% and 20% and the median move rise from band 1 to 5 (SC-005); calibration
   charts per event; "chances in order: True" (SC-006).
5. **Section 9**: the strongest inputs make sense; the leak check passes; the check with and
   without long windows.
6. **Section 9b**: the family and direction checks and one verdict per hypothesis H-R1 to H-R6.
7. **Section 10**: the frozen model (target year 2023) saved; the dry run scores every eligible
   2023+ results-eve row (SC-007); "two runs identical: True" (SC-002); the findings.
8. MLflow: `uv run mlflow ui --backend-store-uri sqlite:///data/mlflow.db` shows experiment
   `006-results-move` with one run per level and test year, the checks and the frozen model.
9. `git status` before committing: the notebook diff shows no outputs (nbstripout).

## After the researcher approves (FR-019)

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q
uv run sentinel train results_move   # the frozen model from the packaged code
```

The notebook, re-run on the packaged code, gives the same numbers.
