# Implementation Plan: Results-day move model

**Branch**: `006-results-move-model` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/006-results-move-model/spec.md` (rewritten 9 Nov)

## Summary

Rebuild `notebooks/006-results-move-model.ipynb` (its instructions on top, ten sections plus 9b,
in the shape of the approved 007 notebook) with the four D60 levels for the results-day move:
the naive baseline `prev4_mean`, a rule (the company's own typical move, shrunk toward the typical
release's when it has few, combined with its ordinary-day volatility), a ridge regression and
LightGBM. **Every level forecasts the log of the move's typical size; three Platt calibrations on
the validation year turn it into the chances of a move above 5%, 10% and 20%**, kept in order
(research R3). The levels are compared on the walk-forward test years 2019–2022 by the mean log
loss of the three chances (V2-41) under the year-by-year one-standard-error rule (V2-50); the
chosen level's releases go into five bands by the chance above 10% (V2-53); the notebook shows
what the model uses, the checks of D60 and the EDA, a verdict per hypothesis H-R1 to H-R6
(V2-46), and freezes the chosen level for the holdout year 2023 with a dry run. Every fitted step
is a `Dated` (V2-49). Runs are logged in MLflow.

The method's open choices were settled on 2016–2018, before every test year (research, design
check): one forecast rather than three direct models, training from 2010, the sector left out
(not point-in-time, R9), fewer trees. One choice waits for the researcher: leaving out the three
release-timing features (R4). Moving the code to `src/sentinel/models/` follows the researcher's
approval (FR-019) and is the last part of this feature.

## Technical Context

**Language/Version**: Python 3.14 (uv, `uv.lock`)

**Primary Dependencies**: pandas, numpy, scikit-learn (ridge, logistic calibration,
preprocessing, metrics), LightGBM, MLflow, matplotlib; project code `sentinel.eda` (`load`,
`features`, `family`, `folds`, `check_folds`, `purge_table`, `redundant_pairs`, `rank_by_year`,
`auc`), `sentinel.models.dated.Dated`, and from the approved 007 the patterns of
`sentinel.models.dilution` (`Boost` with trees chosen on the validation year, `Bands`,
`provenance`, `save`, `load`). No new dependency.

**Storage**: reads `data/exports/ml/results_move.parquet`, `latest.parquet`,
`feature_snapshot.parquet` (private, git-ignored); writes only the MLflow store `data/mlflow.db`
and `data/mlartifacts/`.

**Testing**: the notebook asserts its invariants (fold blocks checked by `eda.check_folds`; counts
equal `eda.purge_table`; no non-feature input; chances in order; calibration slopes positive; two
final fits identical; dry run scores every eligible row). Unit tests come with the move to
`src/sentinel/models/results_move.py` (FR-019), as `tests/unit/test_models_dilution.py`.

**Target Platform**: the researcher's WSL machine (16 cores, 10 GB; everything under the 5 GB cap,
LightGBM on 8 threads).

**Project Type**: data-science notebook inside the existing pipeline repository, then a model
module and a command.

**Performance Goals**: the notebook runs start to finish in under about 30 minutes (LightGBM fits
took 4–7 seconds in the design check; the hypothesis checks are about 140 fits).

**Constraints**: deterministic (sorted rows, `SEED = 0`, LightGBM `deterministic=True`, fixed
threads); no 2023+ move computed or read; outputs never committed (nbstripout); written findings
quote aggregates only.

**Scale/Scope**: 156,926 learnable releases × 97 inputs (94 if R4 is accepted); 4 folds × 4
levels; grids: ridge 4, rule 3, LightGBM 4 settings × 8 tree counts; hypothesis checks 6 families
× 5 seeds × 4 folds.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I Point-in-time | inputs are the export's as-of-close features and `prev4_mean`, `n_prev` (checked: every earlier move ended before `as_of`); `cum_split_after` and `sector` (current SIC) excluded (R1, R9); every fitted step a `Dated` | ✅ |
| II Every question covers what trades | universe = `eligible` releases (no foreign filers by definition: they file no 8-K item 2.02); no other question's data limits it | ✅ |
| III Survivorship-complete | releases of disappeared companies are in the export and kept | ✅ |
| IV Honest evaluation | D60 levels, purged walk-forward 2019–2022, year-by-year one-SE rule, calibration, five bands with hit rates; method choices made on 2016–2018 only; holdout not computed; chances never a bare number; deterministic | ✅ |
| V Reproducibility | MLflow runs with git commit, export date and data hash; the design check is a script in this folder; locked dependencies | ✅ |
| VI Lawful data use | outputs stripped; aggregates only; nothing published | ✅ |
| VII Simplicity | no new dependency; one forecast per level instead of three models (R3) | ✅ |

Re-check after design: unchanged, all pass. As in 007, the notebook rule "never write to `data/`"
yields to MLflow's store in `data/` (007 research R9).

## Project Structure

### Documentation (this feature)

```text
specs/006-results-move-model/
├── spec.md               # rewritten 9 Nov
├── plan.md               # this file
├── research.md           # decisions R1–R12 and the design check
├── design_check.py       # the design check on 2016–2018 (research)
├── data-model.md         # rows, folds, levels, chances, bands, frozen model
├── quickstart.md         # how to run and what to check
├── contracts/
│   └── model-contract.md # ResultsMoveModel and predict(model, rows), for 009 and 010
├── checklists/requirements.md
└── tasks.md              # /speckit-tasks
```

### Source Code (repository root)

```text
notebooks/
└── 006-results-move-model.ipynb   # rebuilt: instructions, sections 1–10 and 9b

src/sentinel/models/               # after the researcher approves (FR-019)
├── results_move.py                #   replaced: ResultsMoveModel, fit, predict, save, load
└── dated.py, dilution.py          #   unchanged (used)
src/sentinel/cli.py                # `sentinel train results_move` builds the frozen model
src/sentinel/scoring/daily.py      # reads the new output (still paused, V2-42)
tests/unit/
├── test_models_results_move.py    # new: rows, Dated cutoffs, chances in order, predict contract
└── test_models.py                 # Gemini's results-move tests replaced

data/                              # git-ignored
├── exports/ml/                    # read only
├── mlflow.db                      # MLflow tracking store (written)
└── mlartifacts/                   # the frozen model object (written)
```

**Structure Decision**: all model work happens in the notebook, as `docs/plan.md` ("Notebooks
and code") requires; its helper code sits in its first cells so the move to
`src/sentinel/models/results_move.py` is a move plus tests after approval. Gemini's
`results_move.py` stays untouched until then (the daily scoring that imports it is paused).

## Complexity Tracking

No constitution violations to justify.
