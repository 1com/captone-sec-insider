# Implementation Plan: Stock Lookup (Product v1, page 2)

**Branch**: `005-stock-lookup` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-stock-lookup/spec.md`

## Summary

A local, read-only web app where a user finds a company by ticker, name or CIK and reads every insider transaction at it in plain English, each insider's holdings over time, and the company's SEC-defined insider-buying events, with a data-as-of date and a glossary (plan §8.6, page 2; planning task 8.1, due 4 November). It also offers the two JSON endpoints the plan names. A new command, `sentinel lookup`, builds a small `data/lookup.duckdb` from an allow-list of SEC-derived warehouse tables, so market prices cannot reach the product and the server never locks the warehouse (research R1–R2). `sentinel serve` runs a FastAPI app with Jinja2 pages and a vendored HTMX file (R3).

## Technical Context

**Language/Version**: Python 3.14, managed with uv

**Primary Dependencies**: FastAPI 0.159.1, Starlette 1.9.0, Jinja2 3.1.6, uvicorn 0.54.0 (all locked already); DuckDB 1.5; HTMX 2.0.4 as one vendored static file; httpx for the test client

**Storage**: `data/lookup.duckdb` (built from `data/warehouse.duckdb`, read-only at run time)

**Testing**: pytest; FastAPI `TestClient` on a lookup file built from the synthetic warehouse fixtures; slow tests on the real lookup file under the memory ceiling

**Target Platform**: this WSL2 machine, local browser; 127.0.0.1 only

**Project Type**: web service (server-rendered pages + JSON) inside the existing `sentinel` package

**Performance Goals**: search results within 1 s of typing; any company page, including the largest (76,529 lines), within 2 s (SC-001, SC-002)

**Constraints**: no market prices or values derived from them (constitution VI); never writes to the warehouse; DuckDB memory limit 3 GB; no network at build or run time; port 8766

**Scale/Scope**: about 20,900 companies, 7.35 M transaction lines, 4.9 M owner rows, 39,498 events; one local user

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How this feature complies | Status |
|---|---|---|
| I Point-in-time | Roles shown are as of each filing date (`core.owner_role`, ASOF); events are the preliminary events with entities and roles as of T. The page describes history; it makes no research decision | Pass |
| II Survivorship | No returns. Companies that no longer trade are searchable by old tickers and names (R7) | Pass |
| III Pre-registration, sealed holdout | No returns, labels, outcomes, scores or hit rates are shown or served (FR-008); no label or holdout table is read | Pass |
| IV Honest statistics | No results are shown | N/A |
| V Reproducibility | The lookup file is rebuilt deterministically by one idempotent command from the warehouse; no network | Pass |
| VI Data use | Only SEC-derived tables are read (allow-list, R2); no Yahoo or Tiingo prices or derived values; guard tests check the allow-list and the absence of price columns; local use only, no redistribution | Pass |
| VII Simplicity | The constitution's stack (FastAPI, Jinja2, HTMX, DuckDB); no new Python dependency; the extra DuckDB file is justified in R1 | Pass |

**Post-design re-check (after Phase 1)**: the data model reads only the R2 tables, the contracts serve no price, outcome or score field, and the commands never use the network. All gates still pass; no complexity to justify.

## Project Structure

### Documentation (this feature)

```text
specs/005-stock-lookup/
├── plan.md              # This file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── http.md          # pages and JSON endpoints
│   └── cli.md           # sentinel lookup, sentinel serve
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/sentinel/
├── api/
│   ├── __init__.py
│   ├── lookup.py        # build data/lookup.duckdb from the R2 allow-list (sentinel lookup)
│   ├── queries.py       # read-only queries: search, transactions page, holdings, events, footnotes, meta
│   ├── glossary.py      # plain-English codes, forms, roles, holding types, event kinds
│   ├── app.py           # FastAPI app: pages and JSON routes, one read-only connection, cursor per request
│   ├── templates/       # base.html, search.html, company.html, partial fragments, glossary.html
│   └── static/          # style.css, htmx.min.js (2.0.4, vendored)
├── cli.py               # + `lookup` and `serve` commands
└── config.py            # + Paths.lookup = data/lookup.duckdb

tests/
├── unit/test_lookup_build.py      # tables, counts, holdings rule, events, determinism
├── unit/test_api.py               # routes, paging, edge cases, P6 and P7 rules
├── guards/test_lookup_no_prices.py # allow-list; no price-like columns; read-only connection
└── integration/test_lookup_real.py # slow: real codes vs glossary, largest page time, PayPal example
```

**Structure Decision**: the app lives in the existing package under `src/sentinel/api/`, the folder plan §8.4 reserves for the product. It reuses `sentinel.config.Paths`, `sentinel.warehouse` (connection limits) and `sentinel.core.symbols.normalise`, and is started through the existing `sentinel` CLI.

## Complexity Tracking

No constitution violations; nothing to justify.
