# Implementation Plan: Project Skeleton, SEC Insider-Data Ingest and Provisional Delisted-Candidate List

**Branch**: `001-skeleton-sec-ingest` | **Date**: 2026-10-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-skeleton-sec-ingest/spec.md`

## Summary

Build the runnable `sentinel` package and three working commands.

1. **`sentinel fetch-sec`** downloads the 83 quarterly SEC Insider Transactions archives (0.93 GB) into `data/raw/sec/insider/`. It runs under a shared limit of 10 requests per second, writes files atomically, makes them read-only and records them in an append-only SHA-256 manifest.
2. **`sentinel fetch-sec-tickers`** saves a dated snapshot of the SEC's company-ticker map.
3. **`sentinel candidates-provisional`** streams the needed tables out of the archives into a scratch DuckDB, applies the pilot's simplified gates (reproduced to within 1% on 2019 Q1, [research.md](research.md) R3) and detects A and B1 events from 2006 onward. It then flags companies missing from the SEC ticker map, checks them in memory against Tiingo's public ticker list and writes a ranked, clearly provisional candidate list with a summary set against the pilot's numbers.

Every other pipeline step is listed in the command help and exits with "not yet implemented". All thresholds live in `config/params.yaml`, which is checked automatically against Appendix E.

## Technical Context

**Language/Version**: Python 3.14.4 (installed system-wide, pinned in `.python-version`), managed with uv 0.11

**Primary Dependencies**: httpx 0.28, duckdb 1.5.x (pinned below 2, [research.md](research.md) R9), pyarrow 25, pyyaml 6, python-dotenv 1.2, typer 0.27. Development only: pytest 9.1, ruff 0.17, respx 0.23

**Storage**:
- Raw files under `data/raw/` with the manifest `data/raw/manifest.jsonl`.
- The scratch DuckDB and provisional outputs under `data/provisional/`.
- `data/` is git-ignored. No warehouse layers are created in this feature.

**Testing**: pytest with offline enforcement (sockets blocked unless a test is marked `network`), respx for HTTP, synthetic zip fixtures built in `tmp_path`, and typer's `CliRunner` for the command line

**Target Platform**: Linux (WSL2) on the researcher's workstation

**Project Type**: single-package command-line tool and data pipeline (`src/` layout)

**Performance Goals**:
- Full download in under 1 hour (SC-004). It is limited by bandwidth: about 1 GB in 83 sequential requests.
- A rerun after a complete download takes under 1 minute (SC-003).
- The candidate run takes under 15 minutes over all 83 quarters.

**Constraints**:
- SEC requests stay at or below 10 per second at all times, with the contact User-Agent on every request.
- No Tiingo data is written to disk.
- Raw files are never modified once stored.
- Tests run with no network access.
- About 3 GB of disk: 0.93 GB raw plus the scratch DuckDB.

**Scale/Scope**:
- About 9 M transaction lines, 11 M footnotes, 5 M submissions and 5.5 M owner rows across 83 quarters.
- About 1 M purchase lines and about 190 k clean filings after the gates.
- Expected output: about 4,000 companies with events and about 1,300 likely-delisted candidates.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this feature complies | Status |
|---|---|---|
| **I. Point-in-Time Integrity** | This feature produces no production events, features or labels. The provisional list uses today's SEC ticker map, which is look-ahead. That is allowed only because its outputs are segregated in `data/provisional/` with `PROVISIONAL` in every name (FR-023), and a test fails if any module outside `sentinel.provisional` and the CLI imports `sentinel.provisional` | Pass |
| **II. Survivorship-Complete Data** | The feature's purpose is to find delisted companies so they can be priced. Companies not found in Tiingo's list are counted and reported, not dropped (FR-022) | Pass |
| **III. Pre-Registration and a Sealed Holdout** | Every numeric value sits in `config/params.yaml`: Appendix E rows with their verbatim register cells, plus labelled `ops` and `provisional` sections. A test checks it against Appendix E (FR-003, FR-004). No returns or prices are touched, so the holdout stays sealed. Holdout-period events are counted only, as in the pilot | Pass |
| **IV. Honest Statistics and Economics** | Not applicable: no returns or inference | N/A |
| **V. Reproducibility** | Raw files are immutable (`0444`) with a SHA-256 manifest. Commands are idempotent, dependencies are locked in `uv.lock`, and output ordering is deterministic. The Tiingo flag cannot be rebuilt offline because the ToS forbids keeping the list. The run records the list's hash and timestamp, and `--no-tiingo` gives a fully offline run. The candidate list is provisional, not a key table, so the offline-rebuild rule is not breached | Pass (see note) |
| **VI. Free, Lawful and Respectful Data Use** | SEC: a shared limiter (target 5 per second, ceiling 10) and the contact User-Agent, with no retry after a 403. Tiingo: the public ticker list is processed in memory only (ToS §1.6(a)). Secrets come only from the git-ignored `.env` and are redacted from logs | Pass |
| **VII. Simplicity and Scope Discipline** | No services and no warehouse. Only the packages this feature needs are created. New small dependencies not in plan §8.3 are typer, python-dotenv and respx (test only), justified in [research.md](research.md) R9 and to be added to the decision log | Pass |

**Note for later features**: Tiingo's Starter-plan ToS §1.6(a) (updated 2026-10-06) forbids storing its data. On 2026-10-22 the researcher decided to buy **one month of Tiingo Power** ($30), which allows storage while the plan is active (§1.6(b)), and to finish the project within that month. Principle VI ("free sources only") must be amended before the price-pull feature is planned. Two consequences: Tiingo data must be deleted when the subscription ends, and the offline-rebuild check (Step 21) must run before then. This feature is unaffected, except that the candidate list now covers every year from 2006, because the 500-symbol budget no longer applies.

**Post-design re-check (after Phase 1)**: all gates still pass. The design adds no services or storage engines beyond the plan's stack, and it confines look-ahead data to the provisional package.

## Project Structure

### Documentation (this feature)

```text
specs/001-skeleton-sec-ingest/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0: live checks of SEC/Tiingo files, versions, decisions
├── data-model.md        # Phase 1: entities, fields, validation, download states
├── quickstart.md        # Phase 1: end-to-end validation guide
├── contracts/
│   ├── cli.md                   # commands, options, exit codes
│   ├── params-schema.md         # config/params.yaml structure and register check
│   ├── raw-manifest.md          # data/raw layout and manifest.jsonl schema
│   └── provisional-outputs.md   # candidate list, events, funnel, summary, run metadata
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
pyproject.toml                    # distribution edgar-sentinel, module sentinel, script `sentinel`
uv.lock
config/
└── params.yaml                   # Appendix E (verbatim register cells) + ops + provisional
src/sentinel/
├── __init__.py
├── cli.py                        # typer app: every plan step grouped by phase; stubs exit 4
├── config.py                     # load .env (secrets) + params.yaml; redaction helper; paths
├── ingest/
│   ├── __init__.py
│   ├── http.py                   # rate limiter, retry policy, streaming download to .part
│   ├── manifest.py               # append / read / verify data/raw/manifest.jsonl; run lock
│   ├── sec_bulk.py               # quarter range, URL discovery, fetch + verify archives
│   ├── sec_reference.py          # company_tickers_exchange.json dated snapshots
│   └── sec_tables.py             # stream a table out of a quarterly zip as text columns
└── provisional/
    ├── __init__.py               # module docstring: look-ahead, never used for research
    ├── load.py                   # zips → scratch DuckDB (dedup by accession / line key)
    ├── gates.py                  # pilot gates + per-quarter funnel (SQL)
    ├── events.py                 # window buyers (owner-set merge), A/B1, cooldown
    ├── tiingo_list.py            # in-memory download + match flags; nothing written
    └── candidates.py             # rank, write outputs, summary vs pilot, run metadata
tests/
├── conftest.py                   # offline socket guard, --run-network flag, fixtures
├── fixtures/                     # tiny synthetic TSV rows with real headers; landing-page HTML
├── unit/
│   ├── test_cli.py
│   ├── test_config.py            # secrets loading, redaction, missing contact
│   ├── test_params_register.py   # Appendix E ↔ params.yaml
│   ├── test_http.py              # limiter, retries, 403 abort, Retry-After
│   ├── test_manifest.py          # append, verify, mismatch, unrecorded, lock
│   ├── test_sec_bulk.py          # URL discovery, atomic write, zip validation, resume
│   ├── test_sec_tables.py        # quotes, checkbox column absent/present
│   ├── test_provisional_gates.py
│   ├── test_provisional_events.py
│   ├── test_tiingo_match.py
│   └── test_candidates.py        # ranking, determinism, PROVISIONAL labelling
├── guards/
│   ├── test_no_provisional_imports.py
│   └── test_secrets_not_tracked.py   # .env ignored and untracked
└── network/
    └── test_sec_live.py          # marked network: one HEAD request to the SEC
data/                              # git-ignored (added to .gitignore in this feature)
├── raw/
│   ├── manifest.jsonl
│   └── sec/
│       ├── insider/2006q1_form345.zip … 2026q3_form345.zip
│       └── reference/company_tickers_exchange_YYYYMMDD.json
└── provisional/                   # see contracts/provisional-outputs.md
```

**Structure Decision**:
- **Packages**: this is a single `src/` package following plan §8.4. Only `ingest/` and `provisional/` are created now. `core/`, `events/`, `labels/` and the rest arrive with their own features (Principle VII).
- **Why `provisional/` is separate**: it is not in §8.4. It is kept apart so that look-ahead code is physically isolated and can be deleted once the production event pipeline (Steps 2–5) exists.
- **Scaffold**: the `main.py` scaffold is removed. The `capstone` project name in `pyproject.toml` becomes `edgar-sentinel`.

## Design Notes

- **Command surface**: see [contracts/cli.md](contracts/cli.md). Implemented in this feature: `check`, `fetch-sec`, `verify-sec`, `fetch-sec-tickers` and `candidates-provisional`. Every other step is a stub.
- **Download state machine**: see [data-model.md](data-model.md). A quarter goes `missing → downloading (.part) → validating → stored (read-only + manifest line)`. Failures leave no file under the final name.
- **Refetch**: `fetch-sec --refetch 2026q3` stores a dated copy (`2026q3_form345__refetch_<UTC>.zip`) with its own manifest line. Readers always use the original copy unless a later decision changes that.
- **Redaction**: `config.redact()` masks the Tiingo key wherever it might appear. Logs use a filter that applies it. The manifest stores no request headers.
- **Speed**: the 83 archives are read in one pass. Only `NONDERIV_TRANS` lines with code `P` are kept, together with the `FOOTNOTES` rows of their accessions. All of `SUBMISSION` is kept (it is needed for the last reported ticker), and from `REPORTINGOWNER` only the accession, owner CIK, relationship and title.

## Schedule (fits the October deadline)

| Date | Work |
|---|---|
| 22–23 Oct | Skeleton, config, parameter register, HTTP and manifest, `fetch-sec`. **Start the real download** as soon as `fetch-sec` passes its tests |
| 24–25 Oct | `sec_tables`, the provisional load and gates, funnel check against A.1 (SC-005) |
| 25–26 Oct | Events, Tiingo matching, ranking, summary against §5.2 and A.3 (SC-006). Explain any gap |
| 27 Oct | Candidate list frozen (SC-008). The price-pull feature starts in Week 2 under the one-month Tiingo Power plan |

## Complexity Tracking

No constitution violations need justifying. The one exception to note is that the Tiingo match flag cannot be rebuilt offline. It is covered under Principle V above: the output is provisional, not a key table, and a `--no-tiingo` offline path exists.
