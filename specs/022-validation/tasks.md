# Tasks: Validation round on named cases

**Input**: specs/022-validation/ (spec.md, plan.md)

## Phase 1: Foundational

- [ ] T001 [P] tests/unit/test_validation.py: each check on a small synthetic database finds the planted case and only it (price-source causes; a return that equals a split; a dilution that equals a split; a first count 100× off; releases closer than 30 days; a Tiingo price 10× its year's median; an insider line over $1 billion without a price)
- [ ] T002 src/sentinel/validation.py: `price_mismatch_causes`, `extreme_returns`, `split_dilution`, `first_count_outliers`, `crowded_releases`, `tiingo_price_jumps`, `unjudged_insider_lines`, `edgar_text`; make T001 pass

## Phase 2: User Story 1 — verdicts (P1)

- [ ] T003 [US1] notebooks/022-validation.ipynb: introduction (what, why, how to run), then sections 1–7: what and why, size (all and eligible training rows), causes, at least three named cases with evidence, verdict
- [ ] T004 [US1] Run it under the memory cap; read every case; write the verdict table and findings

## Phase 3: User Story 2 — rules (P1)

- [ ] T005 [US2] Log each problem as a proposal in docs/decisions.md (V2-28 onwards) with counts and a named example; ask the researcher
- [ ] T006 [US2] Implement the accepted rules with tests (point-in-time), rebuild under the cap, re-run the EDA and validation notebooks, update findings

## Phase 4: Polish

- [ ] T007 Update docs/plan.md, AGENTS.md (where things stand), README; ruff, format, tests; commit and push the branch
