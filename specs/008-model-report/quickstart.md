# Quickstart: Model report (008)

## Regenerate from a fresh clone plus the data (FR-011)

1. Build the data (`sentinel build …`, `sentinel export`; README) so `data/exports/ml/` exists.
2. Run the three model notebooks, one after the other, under the memory cap; each records its
   report tables in MLflow (`data/mlflow.db`):

   ```bash
   for nb in 007-dilution-model 006-results-move-model 005-volatility-model; do
     systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace notebooks/$nb.ipynb
   done
   ```

3. Write the report and the model card data:

   ```bash
   uv run sentinel report
   ```

   Expected: `docs/report/model_report.md`, `docs/report/figures/*.png`,
   `docs/report/model_card.json`, in seconds. A second run gives identical files.

## What to check

- Each question's section names its record (experiment, run, commit, export date, data hash).
- The results tables equal the notebooks' (spot-check one table per question).
- The holdout sections say "not run yet" until 010 has run.
- `git diff docs/report/` after a re-run shows only what the records changed.
