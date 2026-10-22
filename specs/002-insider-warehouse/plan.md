# Implementation Plan: Insider Warehouse

**Branch**: `002-insider-warehouse` | **Date**: 2026-10-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-insider-warehouse/spec.md`

## Summary

Build the production insider layers of `data/warehouse.duckdb` from the 83 stored archives, with one CLI command per plan step:

1. **`sentinel stage`** (Step 2) types all 8 SEC tables, 37.9 M rows, into schema `stg`. Values that fail conversion go to `stg.conversion_issue`, and row counts are checked against the files.
2. **`sentinel entities`** (Step 3) builds point-in-time entities with an incremental union-find per issuer (`core.entity_member`), and owner roles as dated intervals (`core.owner_role`).
3. **`sentinel gates`** (Step 4) builds `core.transaction` (every non-derivative line, with flags for G1–G6), `core.clean_purchase` (per entity per filing, with holdings before and after for F7) and `audit.funnel`.
4. **`sentinel detect-prelim`** (Step 5) writes preliminary A/B1/B2 events, with entities and roles as of T, to `evt.prelim_event`.
5. **`sentinel symbols`** (Step 6) builds `core.symbol_map` from SEC data only. **`sentinel fetch-headers`** fetches about 20,000 EDGAR headers for signal filings from 2012 onward, at 8 requests per second, into `data/raw/sec/headers/`, and parses them into `core.filing_header`.
6. **`sentinel audit sheets|summary`** and **`sentinel compare-provisional`** produce the hand-audit sheets and the comparison with feature 001.

There are no new dependencies. A full offline rebuild is estimated at under 10 minutes, against a target of 30.

## Technical Context

**Language/Version**: Python 3.14.4, uv

**Primary Dependencies**: duckdb 1.5.x (ASOF joins, window functions), pyarrow 25 (streaming the TSVs through feature 001's `sec_tables`), httpx, typer, pyyaml. No additions.

**Storage**:
- `data/warehouse.duckdb`, with schemas `stg`, `core`, `evt` and `audit`.
- Raw headers under `data/raw/sec/headers/`, recorded in the manifest.
- Audit sheets and the comparison report under `specs/002-insider-warehouse/`, committed.

**Testing**:
- pytest offline, using synthetic zips built with feature 001's `build_quarter_zip`.
- Builders take `cutoff` and `issuers` arguments for the truncation tests.
- Tests that need the real warehouse are marked `slow` and skipped when it is absent. Network tests are marked `network`.

**Target Platform**: Linux (WSL2), the researcher's workstation

**Project Type**: single-package CLI and data pipeline (extends `src/sentinel/`)

**Performance Goals**:
- Full rebuild (stage → detect-prelim → symbols) in under 30 minutes (SC-008); about 10 minutes expected.
- Header fetch about 40 minutes, one-off, resumable, in the background.

**Constraints**:
- No future data in any point-in-time table (truncation test).
- SEC rules: at most 10 requests per second (headers target 8), contact User-Agent, stop on 403.
- No Tiingo data written to disk.
- `sentinel.provisional` is never imported by production code (guard test).
- Shared helpers (`normalise`, Tiingo matching) move to `sentinel.core.symbols`.

**Scale/Scope**:
- About 38 M staged rows and about 7.4 M core transactions.
- About 190 k clean purchases.
- Roughly 25 k preliminary events, about 20 k of them from 2012 onward.
- About 5–6 k event companies in the symbol map.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this feature complies | Status |
|---|---|---|
| **I. Point-in-Time Integrity** | Entities, roles, clean purchases and events at T use only filings dated on or before T: ASOF lookups over dated membership and role intervals, with entity and role evaluated *at T*. A truncation test runs on synthetic cases and on 20 real (issuer, T) pairs (FR-023). Every derived row carries its filing date. SIC and acceptance time come from each signal filing's own header | Pass |
| **II. Survivorship-Complete Data** | Every issuer is kept, delisted or not. The symbol map lists unmatched companies with reasons instead of dropping them (FR-017) | Pass |
| **III. Pre-Registration and a Sealed Holdout** | All thresholds come from `registered`. The keyword rules and the preliminary cooldown move into a new `rules` section that `prereg-v1` will lock. No prices, labels or outcomes are produced, so the holdout stays sealed. Holdout-period filings are staged and counted only | Pass |
| **IV. Honest Statistics** | Not applicable (no returns) | N/A |
| **V. Reproducibility** | Every layer is rebuilt deterministically from `data/raw` by idempotent commands. Headers are stored raw with manifest lines. Seeds are fixed for audit samples and truncation pairs | Pass |
| **VI. Lawful, Low-Cost and Respectful Data Use** | SEC: rate limiter (8 per second target, 10 ceiling), contact User-Agent, stop on 403. Tiingo: the list is used in memory only for a coverage report, and the stored symbol map is SEC-derived | Pass |
| **VII. Simplicity** | Same stack, no new dependencies. One warehouse file. Derivative lines stay in `stg` until a feature needs them | Pass |

**Post-design re-check**: still passes. The `rules` section and the shared `sentinel.core.symbols` module add no complexity that needs justifying.

## Project Structure

### Documentation (this feature)

```text
specs/002-insider-warehouse/
├── spec.md
├── plan.md                  # this file
├── research.md              # R1–R13: live checks and decisions
├── data-model.md            # warehouse tables, keys, validity rules
├── quickstart.md            # end-to-end validation guide
├── contracts/
│   ├── cli.md               # new and changed commands
│   ├── warehouse-schema.md  # stg/core/evt/audit tables and invariants
│   ├── params-rules.md      # the new `rules` section
│   └── audit-sheets.md      # audit CSV layouts and the summary
├── audits/                  # generated sheets + researcher verdicts (committed)
├── comparison.md            # production vs provisional events (generated, committed)
├── run-notes.md             # results of the real runs
├── checklists/requirements.md
└── tasks.md                 # /speckit-tasks
```

### Source Code (repository root)

```text
src/sentinel/
├── cli.py                    # + stage, entities, gates, detect-prelim, symbols,
│                             #   fetch-headers, audit, compare-provisional
├── config.py                 # SECTIONS gains "rules"; Paths gains warehouse, headers, audits
├── warehouse.py              # connect(), schema creation, table helpers
├── ingest/
│   ├── manifest.py           # + Manifest class (index loaded once; per-line fsync)
│   └── sec_headers.py        # fetch + parse EDGAR index headers
├── core/
│   ├── __init__.py
│   ├── stage.py              # Step 2: archives → stg.*, conversion issues, row checks, drift report
│   ├── entities.py           # Step 3: union-find memberships + owner role intervals
│   ├── gates.py              # Step 4: core.transaction, clean purchases, holdings, funnel
│   ├── symbols.py            # Step 6: symbol map; shared normalise() and Tiingo matching
│   └── audit.py              # audit sheets and summary
└── events/
    ├── __init__.py
    ├── prelim.py             # Step 5: A/B1/B2 with entities and roles as of T
    └── compare.py            # comparison with provisional events (reads the parquet file)
tests/
├── unit/
│   ├── test_stage.py         # typing, conversion issues, drift, row counts, determinism
│   ├── test_entities.py      # joint filers, later merges, same-day filings, roles, promotions
│   ├── test_core_gates.py    # every gate, cited footnotes, holdings before/after, funnel
│   ├── test_prelim_events.py # A/B1/B2, officer/director rule, 10%-only, cooldown
│   ├── test_symbols.py       # listed/OTC/delisted/unmatched, date ranges, no Tiingo on disk
│   ├── test_sec_headers.py   # parse SIC/acceptance, resume, rate, 403
│   ├── test_audit.py         # sheet layout, seeds, summary rates
│   └── test_truncation.py    # synthetic truncation cases
├── integration/
│   └── test_truncation_real.py   # @slow: 20 real (issuer, T) pairs on the warehouse
└── guards/                   # existing guards (provisional imports, secrets) still apply
```

**Structure Decision**:
- **Packages**: new `sentinel.core` and `sentinel.events` packages, as laid out in plan §8.4. The provisional package is untouched.
- **Shared helpers**: `normalise()` and the Tiingo matching move to `sentinel.core.symbols`. `sentinel.provisional.tiingo_list` re-exports them, so feature 001 keeps working while the guard test still forbids imports in the other direction.

## Design Notes

- **Build order and idempotence**:
  - Each command drops and recreates only its own tables: `stage` → `stg.*`, `entities` → `core.entity_member` and `core.owner_role`, and so on.
  - `sentinel build` runs Steps 2–6, without the header fetch, in order.
  - A `core.build_log` table records each step's run time, input fingerprint and row counts.
- **Large inserts**: each quarter's pyarrow table is registered in DuckDB and inserted with casts in SQL. Conversion failures are captured with a second pass over the same registered table: rows where the raw text is non-empty and the typed value is null.
- **Entities in Python**: memberships are produced as an Arrow table and bulk-inserted. Same-day filings are applied together before membership rows are emitted.
- **Events in Python, per issuer**: clean purchases with owner sets, plus ASOF entity and role lookups done in SQL for each candidate (purchase, T) pair, then counting in Python. The per-issuer data is small.
- **Holdings arithmetic**: in SQL over `core.transaction` and `stg.nonderiv_holding` for the filing, as in research R5. The count of null "before" values is reported.
- **Comparison and audits**: these write committed artifacts under `specs/002-insider-warehouse/`. Re-running overwrites `comparison.md` and creates new audit sheets only on request (`--force`), so completed verdicts are never lost.

## Schedule (Week 1)

| Date | Work |
|---|---|
| 22–23 Oct | `rules` params, `warehouse.py`, `stage` with tests; run staging and check counts (SC-001) |
| 23–24 Oct | `entities` and `gates` with tests; funnel (SC-002); generate audit sheets → **researcher audits, about 1–2 h** |
| 24–25 Oct | `detect-prelim`, comparison (SC-005); start `fetch-headers` in the background |
| 25–26 Oct | `symbols`, truncation tests (SC-003), audit summary (SC-004) |
| 27–28 Oct | Polish, run notes, quickstart, commits. Feature 003 (prices, buy the Tiingo month) can start 29 Oct |

## Complexity Tracking

No constitution violations to justify.
