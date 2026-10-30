# Implementation Plan: EDA and data-quality report

**Branch**: `004-eda` | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-eda/spec.md`

## Summary

Three Jupyter notebooks, one per training set in `data/exports/ml/` (volatility, results-day move,
dilution), each a full exploratory analysis of the development rows that ends with written
findings: what is clean, proposed cleaning rules with row counts, and modelling advice for 005–007.
The repeated pieces (loading within the memory cap, feature families, missing-value, decile,
rank-correlation, stability and purge tables) live in one small tested module,
`src/sentinel/eda.py`, so the three notebooks stay short and agree on method. The notebooks run
with one command each (`jupyter nbconvert --execute`) and are committed without outputs
(`nbstripout` as a git filter).

## Technical Context

**Language/Version**: Python 3.14 (uv-managed, as the project)

**Primary Dependencies**: pandas, numpy, scipy, scikit-learn (AUC), matplotlib (all already
locked); dev group adds `nbconvert` (runs a notebook start to finish) and `nbstripout` (removes
outputs before commit)

**Storage**: reads `data/exports/ml/{volatility,results_move,dilution}.parquet` (private export,
git-ignored); writes nothing to `data/`

**Testing**: pytest unit tests for `sentinel.eda` on synthetic frames; each notebook executed end to
end by `nbconvert` as its own check

**Target Platform**: WSL2 on this machine; VS Code or Jupyter to read the executed notebooks

**Project Type**: single project (existing `src/sentinel/` package) plus `notebooks/`

**Performance Goals**: each notebook under 10 minutes (SC-001)

**Constraints**: 5 GB memory cap (systemd scope, no swap); development rows only (as of
2022-12-31 or earlier); no outputs committed; findings quote aggregates only (Tiingo terms)

**Scale/Scope**: 734,203 / 171,524 / 713,830 rows × 110–114 columns; about 100 features each

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this feature complies | Before | After design |
|---|---|---|---|
| I. Point-in-time | Reads features as built (already point-in-time); the leakage section checks that no feature beats the answer implausibly and that `window_end` / `close_after` lie after `as_of` | PASS | PASS |
| II. Covers what trades | Coverage is reported by coverage level and filer type, including foreign and price-only rows; missing features of foreign filers are explained, not filled | PASS | PASS |
| III. Survivorship | Coverage by year includes companies that later disappeared (rows are not filtered by today's listing) | PASS | PASS |
| IV. Honest evaluation | Only development rows (answers exist only for windows ending by 2022-12-31; the notebooks also filter `as_of <= 2022-12-31`); the private reference copies (002) are not read; the baseline is measured on the test years 2019–2022 for information, no model is chosen | PASS | PASS |
| V. Reproducibility | One command per notebook; deterministic (fixed seed for any sample); helpers tested; dependencies locked in `uv.lock` | PASS | PASS |
| VI. Data use | Notebooks committed without outputs; findings give counts, shares, medians, correlations only | PASS | PASS |
| VII. Simplicity | Two dev-only tools (`nbconvert`, `nbstripout`), named in docs/plan.md already; no new service | PASS | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/004-eda/
├── plan.md              # this file
├── research.md          # Phase 0: measures, memory, sections, stripping
├── data-model.md        # Phase 1: the three training sets and the finding record
├── quickstart.md        # Phase 1: how to run and check
├── contracts/
│   └── notebook-sections.md   # the section order every notebook follows
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (speckit-tasks)
```

### Source Code (repository root)

```text
src/sentinel/
└── eda.py                       # new: shared EDA helpers (load, families, tables)

notebooks/
├── 004-eda-volatility.ipynb     # new
├── 004-eda-results-move.ipynb   # new
└── 004-eda-dilution.ipynb       # new

tests/unit/
└── test_eda.py                  # new: helpers on synthetic frames

.gitattributes                   # new: nbstripout filter for *.ipynb
pyproject.toml, uv.lock          # dev group: nbconvert, nbstripout
docs/decisions.md                # proposed cleaning rules logged (V2-22 onwards)
docs/plan.md, README.md          # 004 owner and status; how to run the notebooks
```

**Structure Decision**: single project. Shared logic in `src/sentinel/eda.py` (tested, importable by
the 008 report later); notebooks hold the narrative, charts and findings only.

## Complexity Tracking

No constitution violations.
