# Implementation Plan: Dilution model

**Branch**: `007-dilution-model` | **Date**: 2026-11-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/007-dilution-model/spec.md`

## Summary

Fill `notebooks/007-dilution-model.ipynb` (ten sections, instructions already in it) with the four
D60 levels for the dilution question: base rate, the offering rule, a logistic regression and
LightGBM, compared on purged walk-forward test years 2019–2022 by log loss with the
one-standard-error rule; calibrate the chosen level (Platt, on the last training year), show five
bands with hit rates, explain what it uses (importance, insider/macro family refits over five
seeds), and freeze it as one object with a `predict(model, rows)` function, dry-run on the
2023+ feature rows. Runs are logged in MLflow. One look-ahead column (`cum_split_after`) is kept
out of the features (research R1). Moving the code to `src/sentinel/models/` comes after the
researcher's approval and is not part of this plan's notebook work.

**Revision of 5 November** (spec FR-017 to FR-019; tasks T032 to T039): the folds come from
`eda.folds` and are checked by `eda.check_folds`; every model, calibration and set of band edges
is a `sentinel.models.dated.Dated` (V2-49), so LightGBM's number of trees is chosen by predicting
the validation year rather than by early stopping; the split-like answers are dropped by code
(V2-40); the level is chosen by one standard error of the yearly differences (V2-50); section 9b
gives a verdict per hypothesis (V2-46). The notebook now also reads the build database once,
read-only, for the split-like answers, and runs on this machine (16 cores, LightGBM on 8 threads,
under the 5 GB cap).

## Technical Context

**Language/Version**: Python 3.14 (uv, `uv.lock`)

**Primary Dependencies**: pandas, numpy, scikit-learn (logistic regression, preprocessing,
metrics), LightGBM (level 3; on macOS it needs the `libomp` runtime, installed 2 Nov, research
R10), MLflow, matplotlib; project helpers `sentinel.eda` (`load`, `features`,
`redundant_pairs`, `purge_table`, `auc`, `top_decile_lift`). No new Python dependency.

**Storage**: reads `data/exports/ml/dilution.parquet`, `latest.parquet`, `feature_snapshot.parquet`
(private, git-ignored); writes only the MLflow store `data/mlflow.db` and `data/mlartifacts/`.

**Testing**: the notebook asserts its own invariants (fold counts equal `eda.purge_table`; no
non-feature column among inputs; two final fits give identical predictions; dry run scores every
eligible row). Unit tests come with the move to `src/sentinel/models/` (FR-016, after approval).

**Target Platform**: the teammate's MacBook (Apple silicon, 24 GB RAM, 10 cores); also the
researcher's WSL machine.

**Project Type**: data-science notebook inside the existing pipeline repository.

**Performance Goals**: the whole notebook runs in under about 30 minutes on the Mac.

**Constraints**: deterministic (sorted rows, `SEED = 0`, LightGBM `deterministic=True`, fixed
threads); no 2023+ answer computed or read; outputs never committed (nbstripout); written
findings quote aggregates only.

**Scale/Scope**: 409,576 learnable rows × 95 features; 4 folds × 4 levels; tuning grids of 3 (C)
and 4 (trees); family check 2 families × 5 seeds × 4 folds.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I Point-in-time | features are the export's as-of-close features; `cum_split_after` (future split ratios) excluded (R1) | ✅ |
| II Every question covers what trades | universe = `eligible_dilution` (V2-27, decided); no other question's data limits it | ✅ |
| III Survivorship-complete | rows of disappeared companies are in the export and kept | ✅ |
| IV Honest evaluation | D60 levels, purged walk-forward 2019–2022, one-SE rule, calibration, five bands; holdout not computed; frozen model ready for 010; deterministic | ✅ |
| V Reproducibility | MLflow runs with git commit, export date and data hash; locked deps | ✅ |
| VI Lawful data use | outputs stripped; aggregates only; nothing published | ✅ |
| VII Simplicity | no new Python dependency or service; `libomp` is the OS runtime LightGBM already requires | ✅ |

Re-check after design: unchanged, all pass. One documented tension (not a violation): the
notebook rule "never write to `data/`" vs the architecture's MLflow store in `data/` (R9).

## Project Structure

### Documentation (this feature)

```text
specs/007-dilution-model/
├── spec.md
├── plan.md              # this file
├── research.md          # decisions R1–R10
├── data-model.md        # rows, folds, levels, bands, frozen model
├── quickstart.md        # how to run and what to expect
├── contracts/
│   └── frozen-model.md  # the saved object and predict(model, rows), for 009 and 010
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
notebooks/
└── 007-dilution-model.ipynb   # filled in this feature: sections 1–10

src/sentinel/models/           # created only after the researcher approves (FR-016)
└── dilution.py                #   DilutionModel, fit, predict (moved from the notebook)

data/                          # git-ignored
├── exports/ml/                # read only
├── mlflow.db                  # MLflow tracking store (written)
└── mlartifacts/               # MLflow artifacts: the frozen model object (written)
```

**Structure Decision**: all work happens in the existing notebook, as `docs/plan.md` ("Notebooks
and code") requires; the helper code lives in its first cells so the move to
`src/sentinel/models/dilution.py` is a cut-and-paste plus tests after approval.

## Complexity Tracking

No constitution violations to justify.
