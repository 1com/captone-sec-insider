# Quickstart: Dilution model (007)

## Prerequisites

- The repository on branch `007-dilution-model`, `uv sync` done.
- The private export unzipped so that `data/exports/ml/dilution.parquet`, `latest.parquet` and
  `feature_snapshot.parquet` exist (bundle `teammate-007-dilution-2026-10-30`).
- nbstripout installed once: `uv run nbstripout --install --attributes .gitattributes`.
- macOS only: `brew install libomp` (LightGBM's OpenMP runtime).

## Run

```bash
# macOS
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/007-dilution-model.ipynb
# WSL (researcher's machine)
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace notebooks/007-dilution-model.ipynb
```

Expected: finishes without errors in roughly 30 minutes or less.

## What to check (maps to the spec's success criteria)

1. **Section 1**: 409,576 rows, 6,300 companies, base rate 9.59%; 95 features, no
   `cum_split_after`.
2. **Section 2**: per test year, train / purged / test counts equal the EDA's purge table
   (e.g. 2019: 243,182 / 19,917 / 39,403).
3. **Sections 3–7**: a table of every level × test year with log loss, AUC, Brier (base rate
   ≈ 0.0867) and lift; the rule's AUC about 0.71–0.74; the named choice with its reason (SC-003,
   SC-004).
4. **Section 8**: five bands per test year, real rate rising from band 1 to 5 (SC-005).
5. **Section 9**: top features make sense; no non-feature input; insider/macro refit table with
   five seeds.
6. **Section 10**: findings in plain words; the frozen model saved; dry run scores every eligible
   2023+ row; "two runs identical: True" (SC-002, SC-006).
7. MLflow: `uv run mlflow ui --backend-store-uri sqlite:///data/mlflow.db` shows experiment
   `007-dilution` with one run per level and test year, the family check and the frozen model.
8. `git status` before committing: the notebook shows no outputs in the diff (nbstripout).
