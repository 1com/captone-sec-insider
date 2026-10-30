---

description: "Task list for 004: EDA and data-quality report"
---

# Tasks: EDA and data-quality report

**Input**: Design documents from `specs/004-eda/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/notebook-sections.md,
quickstart.md

**Tests**: unit tests for the shared helpers (plan.md: "Testing"); each notebook is checked by
running it end to end.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1 volatility, US2 results-day move, US3 dilution, US4 cleaning rules
- Notebooks run under the memory cap:
  `systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace <notebook>`

---

## Phase 1: Setup

- [X] T001 Add `nbconvert` and `nbstripout` to the dev group in pyproject.toml and lock (`uv add --dev nbconvert nbstripout`)
- [X] T002 Install the output filter: `uv run nbstripout --install --attributes .gitattributes`; commit .gitattributes (`*.ipynb filter=nbstripout`, diff and merge settings as written by nbstripout)

---

## Phase 2: Foundational (blocks every story)

- [X] T003 [P] tests/unit/test_eda.py on synthetic frames: `load` keeps only `as_of <= 2022-12-31`; every feature column gets exactly one family and identifiers, flags and answers none; `missing_table` shares; `extremes_table` counts per rule; `rank_table` Spearman overall and per year; `decile_table` 10 rows with the answer's mean and median; `redundant_pairs` finds a duplicated column at |ρ| ≥ 0.9; `purge_table` drops training rows whose window ends on or after 1 January of the test year
- [X] T004 Create src/sentinel/eda.py (research R3, R4, R7; data-model.md): `EXPORT`, `DEV_END = 2022-12-31`, `TEST_YEARS` from `config/risk_params.yaml`; `load(name, columns=None)` (pyarrow, development rows only, sorted by `cik`, `as_of`); `FAMILIES` and `family(col)`; `features(frame)`; `size_band` (micro < $300 M, small to $2 B, mid to $10 B, large, unknown); `coverage_table`; `eligibility_reasons` (not active filer, excluded, close < $1, `addv20` < $10,000, `sessions_listed` < 63); `missing_table`; `extremes_table` (rules of data-model.md: counts < 0, non-finite ratios, `close < 0`, `market_cap <= 0`, answers out of range) with 1st / 99th percentiles; `rank_table`; `decile_table`; `redundant_pairs`; `purge_table`; small plotting helpers on matplotlib; make T003 pass

**Checkpoint**: `uv run pytest -q tests/unit/test_eda.py` passes; ruff passes.

---

## Phase 3: User Story 1 — the volatility set (P1) 🎯 MVP

**Goal**: notebooks/004-eda-volatility.ipynb with every section of contracts/notebook-sections.md
and its findings.

**Independent Test**: the notebook runs start to finish with one command under the cap in under 10
minutes and ends with its Findings.

- [X] T005 [US1] Write notebooks/004-eda-volatility.ipynb sections 0–10 (contract): baseline `vol_63`; measures of research R1 (log errors, Spearman, share within ±25%) overall and per test year; answer on a log scale; check `window_end > as_of`
- [X] T006 [US1] Run it under the cap (quickstart); fix errors; record its duration
- [X] T007 [US1] Write section 11, Findings, from the executed outputs (aggregates only): clean, cleaning rules with rows affected, modelling advice for 005, open questions; terms explained in plain words

**Checkpoint**: US1 complete; the volatility set is understood.

---

## Phase 4: User Story 2 — the results-day move set (P2)

**Goal**: notebooks/004-eda-results-move.ipynb, same contract.

**Independent Test**: as US1.

- [X] T008 [P] [US2] Write notebooks/004-eda-results-move.ipynb sections 0–10: baseline `prev4_mean` where `n_prev` ≥ 1 (share with 4, 1–3, 0 earlier moves); constant-median floor; absolute errors and Spearman per test year; timing (`report_date` → `filing_date` → `close_after`) and `close_after > as_of`; move skew and its largest values
- [X] T009 [US2] Run it under the cap; fix errors; record its duration
- [X] T010 [US2] Write section 11, Findings (as T007), advice for 006

---

## Phase 5: User Story 3 — the dilution set (P3)

**Goal**: notebooks/004-eda-dilution.ipynb, same contract.

**Independent Test**: as US1.

- [X] T011 [P] [US3] Write notebooks/004-eda-dilution.ipynb sections 0–10: base rate overall and by year, sector, size, filer type; single-feature AUC and top-decile lift; simple rules (loss-making and short cash runway; recent offering or shelf) with their AUC and lift; Brier score of the base rate; share-count anomalies (`share_growth_12m` extremes, split months via `cum_split_after` changes) against the answer
- [X] T012 [US3] Run it under the cap; fix errors; record its duration
- [X] T013 [US3] Write section 11, Findings (as T007), advice for 007

---

## Phase 6: User Story 4 — findings into pipeline rules (P2)

**Goal**: every proposed cleaning rule logged for a decision.

**Independent Test**: each rule in the three Findings sections has an entry with its reason and
rows affected.

- [ ] T014 [US4] Log the proposed cleaning rules in docs/decisions.md as proposals (V2-22 onwards: what, why, rows and companies affected, which set), marked "proposed, not implemented"; implementing them is a separate change with tests (FR-015)

---

## Phase 7: Polish & cross-cutting

- [ ] T015 [P] Update docs/plan.md (004 owner: coding agent with the researcher; status; next steps) and README.md (how to run the notebooks)
- [ ] T016 Run `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest -q`; confirm the staged notebooks hold no outputs (quickstart check 3)
- [ ] T017 Mark tasks done here, merge `004-eda` into `main`, delete the branch, comment on issue #76

---

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T004) → US1, US2, US3 (independent of each other) → US4
  (needs all three Findings) → Polish.
- Within a story: write → run → findings.

## Parallel Opportunities

- T003 with T001–T002.
- T005, T008, T011 (three notebooks) once T004 is done; their runs one at a time (memory cap).

## Implementation Strategy

### MVP first

Setup, Foundational, then US1 (volatility): the first model starts on it.

### Incremental delivery

1. Volatility notebook and findings.
2. Results-day move.
3. Dilution.
4. Cleaning rules logged; plan and README updated; merge.

## Notes

- Never commit `data/` or notebook outputs; findings quote aggregates only.
- The notebooks read only `data/exports/ml/`; never the private reference copies (002).
