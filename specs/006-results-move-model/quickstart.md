# Quickstart: Results-day move model (006)

## Prerequisites

- Private Parquet export in `data/exports/ml/results_move.parquet`, `latest.parquet`, and
  `feature_snapshot.parquet` (built by `sentinel export`).
- `nbstripout` filter installed (`.gitattributes`).

## 1. Run the model notebook (Phase 1 — for researcher review)

Always run under the 5 GB memory cap with no swap:

```bash
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 \
  uv run jupyter nbconvert --to notebook --execute --inplace notebooks/006-results-move-model.ipynb
```

## 2. Verify notebook quality and determinism

1. Open `notebooks/006-results-move-model.ipynb` in VS Code to inspect all tables, charts and
   section 10 Findings.
2. Re-run the command above and confirm the comparison table and band hit-rate numbers are
   identical.
3. Confirm `git diff` on staged notebooks contains no output cells (`nbstripout`).

## 3. Run package tests and CLI (Phase 2 — after researcher approval)

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q tests/unit/test_results_move_model.py
```
