# Quickstart: Validate Feature 001

A step-by-step check that the feature works end to end. Formats are in [contracts/](contracts/), and entities in [data-model.md](data-model.md).

## Prerequisites

- Python 3.14.4 and uv 0.11 or later.
- `.env` at the repository root (git-ignored) containing:
  ```
  SEC_USER_AGENT="Your Name your@email"
  TIINGO_API=...            # optional for this feature
  ```
- About 3 GB of free disk space and a network connection for the fetch steps.

## 1. Set up and inspect (SC-001, User Story 3)

```bash
uv sync
uv run sentinel --help        # every step 0–21 + P, grouped by phase
uv run sentinel check         # OK/WARN/FAIL lines; exit 0
uv run sentinel stage; echo $?   # "not yet implemented — plan Step 2"; prints 4
```

## 2. Tests and lint, offline (FR-007, SC-009)

```bash
uv run pytest                 # sockets are blocked; all pass
uv run ruff check .
git ls-files .env             # prints nothing
git log -p | grep -c "$(grep '^TIINGO_API=' .env | cut -d= -f2-)"   # prints 0
```

## 3. Download the archive (User Story 1, SC-002 to SC-004)

```bash
uv run sentinel fetch-sec --dry-run   # 83 quarters with resolved URLs
time uv run sentinel fetch-sec        # 83 stored; under 1 hour
uv run sentinel verify-sec            # ok=83 mismatch=0 missing=0 unrecorded=0
time uv run sentinel fetch-sec        # 83 skipped (verified), 0 fetched; under 1 minute
wc -l data/raw/manifest.jsonl         # 83 (plus ticker snapshots, if fetched)
```

**Resume check**: start `fetch-sec` on an empty `data/raw/sec/insider/`, interrupt it with Ctrl-C after a few quarters, and run it again. Only the missing quarters should be fetched, and no `.part` file should remain.

**Rate check**: the request log never shows more than 10 SEC requests in any one second.

## 4. Build the candidate list (User Story 2, SC-005 to SC-008)

```bash
uv run sentinel fetch-sec-tickers
uv run sentinel candidates-provisional
cat data/provisional/summary_PROVISIONAL.md
```

Expected:
- 2019 Q1 and 2023 Q1 funnel rows within 1% of Appendix A.1. Any wider gap is marked **CHECK** and explained.
- Every §5.2 row (start years 2006 to 2016) within ±15% of the pilot; for example, 2016 is 11,162 events, 4,039 companies, 955 matched and 340 unmatched. Any wider gap is marked **CHECK** and explained before the list is used.
- `delisted_candidates_PROVISIONAL.csv` sorted with tier 1 (clusters) first.

**Determinism check (SC-007)**:

```bash
uv run sentinel candidates-provisional --no-tiingo && sha256sum data/provisional/delisted_candidates_PROVISIONAL.csv
uv run sentinel candidates-provisional --no-tiingo && sha256sum data/provisional/delisted_candidates_PROVISIONAL.csv   # same hash
```

**Tiingo storage check**: `find data -iname '*tiingo*'` finds nothing, because the Tiingo list is never written.

## 5. Done when

- Every command above behaves as described.
- The candidate list exists by 27 October 2026 (SC-008).
- Any **CHECK** marks in the summary are explained in the run notes.
