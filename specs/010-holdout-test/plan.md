# Implementation Plan: The holdout test

**Branch**: `010-holdout-test` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

## Summary

One guarded command, `sentinel holdout`, with three modes: `--freeze-levels` (once, now: proves the
packaged simpler levels reproduce the notebooks' recorded test-year numbers on the kept export of
9 November, then freezes them for 2023 in MLflow), `--check` (any time: verifies everything except
the answers) and `--run` (once, 16 November: computes the 2023+ answers in memory with the
development label code, scores the frozen models of V2-59 and the frozen levels of V2-60, records
the results for the model report and appends the log). Research R1–R5.

## Technical Context

**Language/Version**: Python 3.14 (uv). **Dependencies**: existing (pandas, numpy, scikit-learn,
LightGBM, MLflow, DuckDB); no new one.

**Storage**: reads `data/frozen/2026-11-09/ml/` (the kept export), `data/sentinel.duckdb`
(read-only, for the 2023+ answers and features), `data/mlflow.db`; writes MLflow runs
(`frozen-levels` in the three experiments; `010-holdout`) and `data/holdout/log.jsonl`.

**Testing**: pytest: the label functions with a later end date; the guard (missing model, changed
parameters, earlier run); the check mode computes no answer; a synthetic run writes records the
report reads.

**Constraints**: under the memory cap; read-only database (not during the daily update); no 2023+
answer written anywhere but the records; aggregates only.

**Performance Goals**: `--freeze-levels` about 15 minutes once; `--run` under 20 minutes.

## Constitution Check

| Principle | How this plan complies | Status |
|---|---|---|
| I Point-in-time | 2023+ answers by the development label code; every level frozen from answers known before 2023 | ✅ |
| IV Honest evaluation | evaluated exactly once, guarded and logged; frozen models unchanged; every level compared; results unedited in the report | ✅ |
| V Reproducibility | the kept export checked by hash; packaged levels proven identical to the notebooks' records | ✅ |
| VI Lawful data use | private data stays in `data/`; records and summary aggregates only | ✅ |

## Project Structure

```text
specs/010-holdout-test/        spec, plan, research, contracts, quickstart, tasks
src/sentinel/models/levels.py  the simpler levels of the three questions (from the notebooks)
src/sentinel/holdout.py        freeze-levels, check, run: the guard, the answers, the scoring, the records
src/sentinel/eda.py            `load(..., folder=)`: read a kept export
src/sentinel/validation.py     `split_dilution(con, rows=)`: the rule on given answers
src/sentinel/cli.py            `sentinel holdout --check | --freeze-levels | --run`
tests/unit/test_holdout.py     the tests above
```

## Complexity Tracking

No constitution violations to justify.
