# Quickstart: Validate Feature 002

**Prerequisites**:
- Feature 001 is complete: 83 archives verified with `sentinel verify-sec`, plus an SEC ticker snapshot.
- `.env` holds `SEC_USER_AGENT`.
- About 5 GB of free disk space.

Contracts: [cli](contracts/cli.md), [warehouse invariants](contracts/warehouse-schema.md), [rules section](contracts/params-rules.md), [audit sheets](contracts/audit-sheets.md).

## 1. Tests (offline)

```bash
uv run pytest                  # unit + guards; slow/network tests skipped
uv run ruff check .
```

## 2. Build the warehouse (SC-001, SC-002, SC-008)

```bash
time uv run sentinel build     # stage → entities → gates → detect-prelim → symbols; < 30 min
```

**Expected**:
- `stage`: 8 tables × 83 quarters with 0 count mismatches (37,937,561 rows), plus the conversion-issue counts per column.
- `gates`: the funnel reconciles. The number of clean purchases is printed (about 190 k expected).
- `detect-prelim`: the A/B1/B2 counts.
- `symbols`: the share of event companies mapped (≥ 95% expected), and the count of unmatched companies.

## 3. Fetch filing headers (SC-007), about 40 minutes, in the background

```bash
uv run sentinel fetch-headers --limit 20     # smoke test
uv run sentinel fetch-headers                # the rest; resumable
uv run sentinel verify-sec                   # headers appear as ok (manifest-checked)
```

**Expected**: headers recorded for at least 99% of signal filings from 2012, with the rest in `core.header_failure`.

## 4. Point-in-time check (SC-003)

```bash
uv run pytest -m slow tests/integration/test_truncation_real.py   # 20 real (issuer, T) pairs
```

## 5. Comparison with feature 001 (SC-005)

```bash
uv run sentinel compare-provisional && cat specs/002-insider-warehouse/comparison.md
```

**Expected**: with the $2 stand-in applied, total clusters are at most 16,513, and every year differing by more than 15% has an explanation.

## 6. Hand audits (SC-004), about 1–2 hours for the researcher

```bash
uv run sentinel audit sheets
# open the three CSVs in specs/002-insider-warehouse/audits/, follow each EDGAR link,
# fill verdict (correct / wrong / unclear) and notes
uv run sentinel audit summary          # agreement ≥ 90% per sheet
```

## 7. Done when

- Every step above meets its expected outcome.
- `run-notes.md` records the counts, timings, audit results and comparison.
- `find data -iname '*tiingo*'` is empty.
- The work is complete by 28 October 2026.
