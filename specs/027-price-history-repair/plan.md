# Implementation Plan: Price history repair, then retrain and test

**Branch**: `027-price-history-repair` | **Date**: 2026-11-11 | **Spec**: [spec.md](spec.md)

## Summary

A company's price history becomes a chain of segments, one per ticker it used, joined where its own
evidence and a continuity check agree (research R1–R3, R10); a history is cut only where another
company really held the ticker, before a hole of over a year, or on blank-check (SPAC) days (R4,
R6, R7); a ticker-day belongs to one company (R5); US companies are priced from their common stock
(R8); the old tickers' prices missing from the raw files are downloaded once from Tiingo (R9); a
`sentinel audit` command measures the problem families after every build (R12). Then the layers are
rebuilt, the three models retrained by their unchanged notebooks and approved again, the holdout's
kept rows and simpler levels renewed, and the holdout test run once (R13, R14).

## Technical Context

**Language/Version**: Python 3.14 (uv). **Dependencies**: existing (DuckDB, pandas, httpx, MLflow);
no new one.

**Storage**: reads and writes `data/sentinel.duckdb` (core layer: `core.price_choice` as segments,
new `core.price_decision`); new raw files under `data/raw/tiingo/former/` and
`data/raw/tiingo/former_meta/` with manifest lines; `data/audit/prices-<date>.json` (private);
`docs/report/data_audit.md` (counts only); later `data/frozen/<date>/ml/` and MLflow runs.

**Testing**: pytest on synthetic worlds: a ticker change joined only when names and the switch
agree; an exchange move and a coverage start do not cut; a concurrent use does not cut and a
sequential one does; one ticker-day one company; a hole cuts unless own evidence covers it;
blank-check days (name, length, $10 share) and Geospace untouched; common stock first for US
filers, ADR pairs untouched; adjusted prices continuous across a switch; a later ticker change
leaves earlier rows unchanged (R11); the audit's counts on a world with one case per family. Named
real cases in `tests/real/test_named_cases.py`. The truncation test and `sentinel verify` as before.

**Constraints**: every heavy step under the memory cap (5 GB, no swap); one writer on the build
database (not during the 10:00 update); Tiingo asked only before 26 Nov; Tiingo-derived values never
in a committed file (the audit's committed summary holds counts only).

**Performance Goals**: the former-ticker download about 12 minutes once; the core price steps
within the rebuild's usual time (about 11 minutes for the core layer); `sentinel audit` under a
minute.

**Scale/Scope**: 7,351 listed and some 120,000 other companies; about 25 million daily prices; 692
tickers to download.

## Constitution Check

| Principle | How this plan complies | Status |
|---|---|---|
| I Point-in-time | features use prices of days up to D only (truncation test unchanged); attribution by who held the ticker that day; a new test: a later ticker change leaves earlier rows unchanged | ✅ |
| II Every question covers what trades | companies priced across their tickers and from their common stock; no question limited by another's data | ✅ |
| III Survivorship-complete history | renamed and disappeared companies keep their histories; coverage by year and status in the audit | ✅ (restores it) |
| IV Honest evaluation | holdout answers still computed only by the one run; models retrained by unchanged notebooks and approved again; levels frozen from the same kept rows | ✅ |
| V Reproducibility | raw downloads with manifest lines; deterministic rules (ties by fixed order); `sentinel verify` identical | ✅ |
| VI Lawful data use | Tiingo inside the paid window; private files stay in `data/`; committed audit summary counts only | ✅ |
| VII Simplicity | no new dependency; one new command (`sentinel audit`) and one fetch mode; extends existing tables | ✅ |

The repair is a deliberate exception to the frozen cleaning (V2-33), decided by the researcher
(V2-65), as V2-63 was.

## Project Structure

```text
specs/027-price-history-repair/   spec, plan, research, data model, contracts, quickstart, tasks
src/sentinel/core/prices.py       segments, joins, cuts, one ticker-day one company, SPAC days, common stock first
src/sentinel/raw/tiingo.py        `fetch_former`: old tickers' prices and descriptions, once
src/sentinel/staging/prices.py    the `former_meta` folder among Tiingo's descriptions
src/sentinel/audit.py             the audit: families, named cases, coverage, JSON and summary
src/sentinel/cli.py               `sentinel audit`; `sentinel fetch tiingo-former`
src/sentinel/holdout.py           the kept export found from the approved records (no fixed date)
src/sentinel/serving/publish.py  `app.stock`: the SPAC merger line (former name, merger day) for the stock page
src/sentinel/web/ (template)      the line "listed through a merger with … on …"
tests/unit/test_core_prices.py, tests/unit/test_audit.py, tests/real/test_named_cases.py
docs/decisions.md, docs/architecture.md, docs/plan.md, README.md, AGENTS.md
```

## Complexity Tracking

No constitution violations to justify.
