# Implementation Plan: Daily data refresh

**Branch**: `001-daily-data-refresh` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-daily-data-refresh/spec.md`

## Summary

Bring every dataset to the latest trading day, complete the price coverage of listed companies, and
keep both true every weekday. v1's downloaders are ported into the raw layer as `sentinel fetch
<source>`; new SEC filings are found through the SEC's nightly master index, with each Form 3/4/5
fetched as its full submission (acceptance time and XML in one ~5 KB file) and parsed into the
quarterly data sets' columns. Yahoo is asked once for the full history of every listed symbol, then
for a 10-day window each day, with the full history fetched again after a split or dividend; Tiingo
does the same for its 1,085 Tiingo-priced companies until 26 November. A listed company's own ticker
is accepted on dates alone, and its history reaches back to its ticker's current listing. `sentinel
update` stages only the new files (newest file wins per key, so staging is the same built at once or
day by day), rebuilds every layer above staging in full (about 15 minutes), publishes, records what
changed, and is checked against a full rebuild by `sentinel verify`. A Windows Task Scheduler task
starts it at 23:00 Berlin time on weekdays, catching up missed days. Details:
[research.md](research.md).

## Technical Context

**Language/Version**: Python 3.14, managed with uv

**Primary Dependencies**: duckdb, pyarrow, pandas, numpy, httpx, yfinance, typer, python-dotenv,
pyyaml; the standard library's `xml.etree.ElementTree` and `gzip` for the new parsers. No new
dependency.

**Storage**: raw files under `data/raw/` with `data/raw/manifest.jsonl`; the DuckDB build database
`data/sentinel.duckdb` (new schemas `stg_sec_form4_daily` and `ops`); `data/serving.duckdb`; Parquet
in `data/exports/`; run logs in `data/logs/`

**Testing**: pytest; HTTP mocked with respx; a stand-in for `yfinance.download`; synthetic raw files
for the update and truncation tests; real Form 4 submissions as fixtures; named real-data checks in
`tests/real` (skipped without the data)

**Target Platform**: WSL2 Ubuntu with systemd on Windows, Berlin time; Windows Task Scheduler reached
through WSL interop (`schtasks.exe`, `wsl.exe`)

**Project Type**: command-line data pipeline (single project)

**Performance Goals**: a weekday update in 30 minutes or less (estimate 27, R10); the one-off refresh
in a few hours (Yahoo's ~1,600 missing histories about 10 minutes, the bulk SEC files about 10, the
October Form 4 backfill about 12,000 submissions, 25 minutes at 8 requests a second)

**Constraints**: 5 GB memory cap per job, DuckDB at 3 GB; SEC at most 10 requests a second (target
8) with the contact in the User-Agent; Tiingo at 2 a second and only inside
`[2026-10-26, 2026-11-26)`; Yahoo in paced batches; at least 20 GB free disk; Tiingo-derived values
private; raw files never edited

**Scale/Scope**: 10,443 SEC-listed symbols; about 4,500 filings indexed a day, of which about 600
ownership filings, 700 detail headers and 50–500 financial-value documents; about 11,000–12,000
priced companies; 30–130 MB of new raw files a weekday

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle or gate | How this plan meets it | Pre-design | Post-design |
|---|---|---|---|
| I. Point-in-time | every new fact gets `known_at`; daily Form 4s take the acceptance time from their submission header; a truncation test is added (task) | PASS | PASS |
| II. Covers what trades | Yahoo asked for every SEC-listed symbol; a listed company's own ticker accepted on dates; history back to the ticker's current listing (R6, R12) | PASS | PASS |
| III. Survivorship-complete | disappeared companies keep their Tiingo history; daily SEC lists date delistings; coverage reported by status and by year (`ops.coverage`) | PASS | PASS |
| IV. Honest evaluation | the update never computes an answer whose window ends after 2022; labels only through the registered, locked step (spec FR-022) | PASS | PASS |
| V. Reproducibility | raw files stored unchanged with manifest lines; staging deterministic (newest file wins); the update equals a full rebuild (`sentinel verify`, unit test); a rerun changes nothing; every file the offline rebuild needs is in the manifest | PASS | PASS |
| VI. Lawful data use | SEC pacing and contact; Tiingo refused outside the paid plan (tested); Yahoo, FRED, FINRA and Cboe paced and not redistributed; secrets only in `.env`, never in paths, URLs or logs | PASS | PASS |
| VII. Simplicity | no new dependency or service; one build database; Windows Task Scheduler is the system's scheduler, set up only by an explicit command | PASS | PASS |
| Quality gates | tests per layer; named real cases (Hitachi, Deutsche Telekom, Standard Life, the calendar's end, Form 4 reconciliation); truncation test; coverage report; ruff | PASS | PASS |

Pre-existing gap, outside this feature: constitution III also asks for an early-ending price series
to be classified (merger, failure, unknown). v2 has no such table yet; no forecast uses it since the
50% fall forecast was dropped (V2-9). It is recorded in `docs/plan.md`'s status.

## Project Structure

### Documentation (this feature)

```text
specs/001-daily-data-refresh/
├── spec.md              # what and why
├── plan.md              # this file
├── research.md          # Phase 0: decisions R1–R16
├── data-model.md        # Phase 1: tables added or changed, run states
├── quickstart.md        # Phase 1: end-to-end checks per success criterion
├── contracts/
│   ├── cli.md           # sentinel fetch, update, status, verify, schedule
│   └── raw-layout.md    # where each source's files go, manifest keys
├── checklists/
│   └── requirements.md  # spec quality checklist
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/sentinel/
├── cli.py                  # + fetch, update, status, verify, schedule
├── db.py                   # + schemas stg_sec_form4_daily, ops
├── raw/
│   ├── http.py, manifest.py   # existing
│   ├── sec.py              # new: ticker list, master index, headers, ownership filings,
│   │                       #      per-company financial values and filing histories, bulk files,
│   │                       #      quarterly Form 4 sets (port of v1 sec_*)
│   ├── yahoo.py            # new: port of v1 yahoo; daily window; refetch after events
│   ├── tiingo.py           # new: port of v1 tiingo; new days; refetch; paid-plan guard
│   └── market.py           # new: FRED, Cboe, FINRA (ports)
├── staging/
│   ├── sec_form4_daily.py  # new: ownership XML → the data sets' tables
│   ├── sec_filings.py      # + daily rows from the index and headers; new registrants
│   ├── sec_headers.py      # + 8-K items and period of report
│   ├── sec_xbrl.py         # + newest financial-values document per company
│   ├── prices.py           # + newest file wins (history base plus daily windows)
│   └── market.py           # + appended short-volume days; compressed copies
├── core/
│   ├── prices.py           # + own-ticker identity; listing start; core.price_coverage
│   └── insider.py          # + quarterly and daily Form 4 sources; core.form4_reconciliation
├── serving/
│   └── publish.py          # + app.freshness; previous copy kept for the change report
└── update/
    ├── run.py              # new: lock, disk check, fetch, staging, rebuild, publish, record
    ├── record.py           # new: ops tables, checksums, change report, log file
    ├── verify.py           # new: full rebuild into a scratch database and comparison
    └── schedule.py         # new: the Windows task (XML), install, remove, show

tests/
├── fixtures/               # + real Form 3/4 submissions, a master index excerpt, headers
├── unit/                   # + test_raw_sec, test_raw_yahoo, test_raw_tiingo, test_raw_market,
│                           #   test_staging_form4_daily, test_update, test_truncation,
│                           #   test_schedule; extended staging and core price tests
└── real/                   # + Hitachi, Deutsche Telekom, Standard Life, calendar end,
                            #   Form 4 reconciliation
```

**Structure Decision**: the existing single project, layer by layer as in `docs/architecture.md`:
fetchers in `raw/`, parsers in `staging/`, rules in `core/`, and a new `update/` package for the
orchestration that spans the layers.

## Complexity Tracking

No constitution violations to justify.
