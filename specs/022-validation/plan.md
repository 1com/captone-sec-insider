# Implementation Plan: Validation round on named cases

**Branch**: `022-validation` | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

## Summary

`src/sentinel/validation.py` holds one function per check (1–7) that returns its cases from the
build database (read-only), each sorted so named examples are picked the same way on every run;
plus `edgar_text(url)` to fetch an SEC document's text live for evidence. The notebook
`notebooks/022-validation.ipynb` runs the seven checks, sorts cases into causes, shows named cases
against their source, and ends with a verdict table and findings. Problems become proposals in
`docs/decisions.md`; accepted ones are implemented with tests.

## Technical Context

**Language**: Python 3.14 (uv) · **Dependencies**: duckdb, pandas, httpx (all locked) ·
**Storage**: reads `data/sentinel.duckdb` read-only; writes nothing to `data/` ·
**Testing**: pytest on synthetic tables for each check; the notebook end to end ·
**Constraints**: 5 GB memory cap, no swap; SEC under 10 requests a second with the contact from
`.env`; outputs stripped on commit.

## Constitution Check

| Principle | How | Result |
|---|---|---|
| I. Point-in-time | Checks may look at later data to *find* problems; every proposed rule must work with what was known at the time | PASS |
| IV. Honest evaluation | No answers after 2022 are read (checks use development rows, prices and filings only) | PASS |
| V. Reproducibility | One command; deterministic case picking; tested check functions | PASS |
| VI. Data use | SEC rate limit and contact; no Tiingo series in written findings | PASS |
| VII. Simplicity | One module, one notebook, no new dependency | PASS |

## Research (decisions)

- **R1 Named cases**: per check, the largest cases by size of the doubt plus well-known companies
  where they appear; sorted deterministically.
- **R2 Price check causes** (check 1): compare the two sources' *closes*: agree within 2% on 90%+
  of days → the adjustment differs (dividends); a steady whole-number ratio (2, 3, 10, …) → a split
  or unit in one source; closes apart on most days → possibly a different stock under the ticker;
  else partly.
- **R3 Split checks** (checks 2, 3): a jump that matches a split factor in the other source, or a
  share-count change that equals the split factor in the window, points to a split read as a
  return or as dilution.
- **R4 Evidence**: SEC filing text via `https://www.sec.gov/Archives/edgar/data/<cik>/<accession>/<document>`
  (from `core.filing.primary_document`), excerpted around the searched words.

## Project Structure

```text
src/sentinel/validation.py        # new: the seven checks and edgar_text
tests/unit/test_validation.py     # new
notebooks/022-validation.ipynb    # new
docs/decisions.md, docs/plan.md, AGENTS.md
```
