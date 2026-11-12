# Quickstart: the holdout test (010)

**Run once on 12 November 2026 (decision V2-69); a second run is refused.** The results are in
`docs/report/model_report.md`; the records in `data/mlflow.db` (experiment `010-holdout`), their
files in `mlruns/9/` at the project root (ignored by git; never delete; a copy in
`data/backup/after-holdout/`). The steps below are kept as the record of how it was run.

The holdout test is run **once**, by the researcher, on **16 November 2026**, after this feature is
merged into `main`. It scores the three approved models (and every simpler level beside them) on
the answers from 2023 on, which no code has computed until then. A second run is refused.

## Before the test (done once, by the agent, before the merge)

1. Keep the export the frozen models were built on (research R1): `data/frozen/<export date>/ml/`
   (each file's hash equals its frozen model's data hash). Since the price repair (027, V2-68) this is
   `data/frozen/2026-11-11/ml/`, with `split_like.parquet` beside it; the first one,
   `data/frozen/2026-11-09/`, is no longer used. Until the test, do not re-execute the model
   notebooks: each execution writes new records, and the test takes the newest ones.
2. Freeze the simpler levels (V2-60), under the memory cap, not while the daily update runs:

   ```bash
   systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run sentinel holdout --freeze-levels
   ```

   Expected (about 15 minutes): per question "N level-years equal the notebook's record (largest
   difference …)" with every difference at most 1e-9, then the levels frozen for 2023 and recorded
   in MLflow (run `frozen-levels` in each model's experiment). Any larger difference refuses.

## Any day: check that everything but the answers is ready

```bash
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run sentinel holdout --check
```

Expected: per question the frozen model (commit, data hash, export date), the frozen levels and the
count of eligible 2023+ feature rows; "the registration lock holds; no holdout run yet; data
current to …". No answer is computed and nothing is written.

## 16 November: the test

1. Let the 10:00 daily update finish (`data/logs/update-2026-11-16.log` says `complete`), or run
   before 10:00: the test reads the build database, which the update holds while it runs.
2. Run the check above; it must pass.
3. Run the test, once:

   ```bash
   systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run sentinel holdout --run
   ```

   Expected (under 20 minutes): progress of the answers ("answers: N/M companies"), then per
   question the rows (eligible, left out, scored) and the deciding measure of every level and of
   the chosen model over all years from 2023; "recorded in MLflow (010-holdout) and logged in
   data/holdout/log.jsonl".
4. Put the results into the model report, unedited:

   ```bash
   uv run sentinel report
   ```

   Each question's section "The holdout test (010)" now shows the run's tables (results per
   calendar year and over all, bands, and the volatility range's coverage).

## What to check afterwards

- `uv run sentinel holdout --run` again is refused ("already run") and changes nothing.
- The report's holdout tables equal the records (MLflow experiment `010-holdout`, artifact
  `holdout.json`).
- No 2023+ answer was written anywhere else: `git status` shows only `docs/report/` changed; the
  label tables and the exports still stop at 2022.

## If the run stops with an error

Nothing is recorded until all three questions are scored, so an error before the end leaves no
record and no log entry: fix the cause (for example, the database was busy) and run again. An
error while the three records are being stored (rare: the MLflow database locked) can leave a
partial record; then the guard refuses every further run. Delete nothing: what to do then is the
researcher's decision, logged in `docs/decisions.md`.
