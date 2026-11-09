# Implementation Plan: Volatility model

**Branch**: `005-volatility-model` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-volatility-model/spec.md`

## Summary

Fill `notebooks/005-volatility-model.ipynb` (its instructions on top, ten sections plus 9b, in
the shape of the approved 006 and 007 notebooks) with the four D60 levels for the next three
months' volatility: the naive baseline (past volatility continues), the mean-reversion rule, a
ridge regression and LightGBM, each forecasting the log of the answer (the ridge and LightGBM as
the change from the log of past volatility, research R3). They are compared on the
walk-forward test years 2019–2022 by the mean absolute error of the log (V2-56) under the
year-by-year one-standard-error rule (V2-50). **Every forecast comes with an 80% range set on the
out-of-sample errors of all earlier years (V2-10)**: the walk-forward is run from 2014, so each
earlier year has been forecast by a model that learned only from the years before it; those years
are not scored, they only give the range its width (research R4). Five bands by the forecast
level carry their real outcomes (D47). The notebook shows what the model uses, a verdict per
hypothesis H-V1 to H-V6 (V2-46), and freezes the chosen level for the holdout year 2023 with a
dry run. Every fitted step is a `Dated` (V2-49). Runs are logged in MLflow.

The method's open choices were settled on 2014–2018, before every test year (research, design
check): the change rather than the level (0.2416 against 0.2468), squared-error loss, the range
pooled over all earlier years (74.9% coverage against 72.1% for the year before and 65.7% for the
training rows' own errors). 005 is built only if the researcher approves it by the evening of Wednesday 11 November
(V2-48). Moving the code to `src/sentinel/models/volatility.py` follows the approval (FR-019).

## Technical Context

**Language/Version**: Python 3.14 (uv, `uv.lock`)

**Primary Dependencies**: pandas, numpy, scikit-learn (linear regression, ridge, preprocessing),
LightGBM, MLflow, matplotlib; project code `sentinel.eda` (`load`, `features`, `family`, `folds`,
`check_folds`, `purge_table`, `redundant_pairs`, `rank_by_year`), `sentinel.models.dated.Dated`,
and from the approved 006 and 007 the patterns of `sentinel.models.results_move` and
`sentinel.models.dilution` (trees chosen on the validation year, `Bands`, `provenance`). No new
dependency.

**Storage**: reads `data/exports/ml/volatility.parquet`, `latest.parquet`,
`feature_snapshot.parquet` (private, git-ignored); writes only the MLflow store `data/mlflow.db`
and `data/mlartifacts/`.

**Testing**: the notebook asserts its invariants (fold blocks checked by `eda.check_folds`; counts
equal `eda.purge_table`; no non-feature input; every range's low below its level below its high;
the range's errors known before each cutoff; two final fits identical; dry run scores every
eligible row). Unit tests come with the move to `src/sentinel/models/volatility.py` (FR-019).

**Target Platform**: the researcher's WSL machine (16 cores, 10 GB; everything under the 5 GB cap,
LightGBM on 8 threads).

**Project Type**: data-science notebook inside the existing pipeline repository, then a model
module and a command.

**Performance Goals**: the notebook runs start to finish in about an hour or less (530,000 rows,
four times 006's; the walk-forward runs from 2014 for the ranges).

**Constraints**: deterministic (sorted rows, `SEED = 0`, LightGBM `deterministic=True`, fixed
threads); no 2023+ answer computed or read; outputs never committed (nbstripout); written
findings quote aggregates only; approval by 11 November evening (V2-48).

**Scale/Scope**: 530,137 learnable rows × 95 features; walk-forward years 2014–2022 (2019–2022
scored) × 4 levels; LightGBM grid 4 settings × up to 8 tree counts; hypothesis checks 5 families
× 5 seeds × 4 folds.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I Point-in-time | inputs are the export's month-end features; `cum_split_after` and `sector` (current SIC) excluded; every fitted step, the range included, is a `Dated` using only answers known before its cutoff | ✅ |
| II Every question covers what trades | universe = `eligible_volatility`, price-only stocks included (V2-26) and reported separately | ✅ |
| III Survivorship-complete | rows of disappeared companies are in the export and kept | ✅ |
| IV Honest evaluation | D60 levels, purged walk-forward 2019–2022, year-by-year one-SE rule, an 80% range scaled out of sample on all earlier years (V2-10), five bands with outcomes; method choices made on 2014–2018 only; holdout not computed; deterministic | ✅ |
| V Reproducibility | MLflow runs with git commit, export date and data hash; the design check is a script in this folder; locked dependencies | ✅ |
| VI Lawful data use | outputs stripped; aggregates only; nothing published | ✅ |
| VII Simplicity | no new dependency; the range is two numbers per fold | ✅ |

Re-check after design: unchanged, all pass.

## Project Structure

### Documentation (this feature)

```text
specs/005-volatility-model/
├── spec.md
├── plan.md               # this file
├── research.md           # decisions R1–R10 and the design check
├── design_check.py       # the design check on 2014–2018
├── data-model.md         # rows, folds, levels, range, bands, frozen model
├── quickstart.md         # how to run and what to check
├── contracts/
│   └── model-contract.md # VolatilityModel and predict(model, rows), for 009 and 010
├── checklists/requirements.md
└── tasks.md              # /speckit-tasks
```

### Source Code (repository root)

```text
notebooks/
└── 005-volatility-model.ipynb     # filled: instructions, sections 1–10 and 9b

src/sentinel/models/               # after the researcher approves (FR-019)
├── volatility.py                  #   replaced: VolatilityModel, fit, predict, save, load
└── dated.py, dilution.py, results_move.py  # unchanged (used)
src/sentinel/cli.py                # `sentinel train volatility` builds the frozen model
src/sentinel/scoring/daily.py      # reads the new output (still paused, V2-42)
tests/unit/
├── test_models_volatility.py      # new
└── test_models.py                 # Gemini's volatility test replaced

data/                              # git-ignored
├── exports/ml/                    # read only
├── mlflow.db                      # MLflow tracking store (written)
└── mlartifacts/                   # the frozen model object (written)
```

**Structure Decision**: all model work happens in the notebook (docs/plan.md, "Notebooks and
code"); its helper code sits in its first cells so the move to `src/sentinel/models/volatility.py`
is a move plus tests after approval. Gemini's `volatility.py` stays untouched until then.

## Complexity Tracking

No constitution violations to justify.
