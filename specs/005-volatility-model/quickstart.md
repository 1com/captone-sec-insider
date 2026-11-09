# Quickstart: Volatility model (005)

## Prerequisites

- The repository on branch `005-volatility-model`, `uv sync` done.
- The private export: `data/exports/ml/volatility.parquet`, `latest.parquet` and
  `feature_snapshot.parquet` (written by the daily update's `sentinel export`).
- nbstripout installed once: `uv run nbstripout --install --attributes .gitattributes`.
- No other heavy job running (the daily update runs at 10:00 on weekdays).

## Run

```bash
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace notebooks/005-volatility-model.ipynb
```

Expected: finishes without errors in about 30–45 minutes. With `SENTINEL_TRIAL=1` it runs one
setting and one seed in a few minutes (a check of the code, logged to the experiment
`005-volatility-trial`).

## What to check (maps to the spec's success criteria)

1. **Section 1**: the learnable rows (530,137 rows, 7,883 companies on the export of 9 Nov), the
   93 zero answers left out, the 95 features, price-only rows counted.
2. **Section 2**: the fold table from `eda.check_folds` for 2014–2022 (2019–2022 scored); counts
   equal `eda.purge_table`.
3. **Sections 3–7**: every level × test year with the mean absolute log error (deciding, V2-56),
   the root mean squared log error, rank correlation and the range's coverage; price-only stocks
   apart; the yearly gaps with their standard errors and the named choice (V2-50) (SC-003,
   SC-004).
4. **Section 8**: the range's coverage per test year (SC-005) and the five bands, median real
   volatility rising from band 1 to 5 (SC-006).
5. **Section 9**: the strongest inputs; the leak check.
6. **Section 9b**: family and direction checks and one verdict per hypothesis H-V1 to H-V6.
7. **Section 10**: the frozen model (target year 2023) saved; the dry run scores every eligible
   2023+ month-end row (SC-007); "two runs identical: True" (SC-002); the findings.
8. MLflow: experiment `005-volatility`.
9. `git status` before committing: the notebook diff shows no outputs (nbstripout).

## After the researcher approves (FR-019)

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q
uv run sentinel train volatility
```
