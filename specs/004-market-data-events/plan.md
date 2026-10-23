# Implementation Plan: Market Data, Final Events, Delistings, Company Financials and Trading Costs

**Branch**: `004-market-data-events` | **Date**: 2026-10-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-market-data-events/spec.md`

## Summary

Add the market side of the study to `data/warehouse.duckdb` (plan Steps 7–10), with one fetch command per source and one offline build command per layer:

1. **Prices** (Step 7).
   - `sentinel fetch-prices --source yahoo` stores about 4,500 tickers plus SPY and IWM, from 2010, as Parquet via yfinance.
   - `--source tiingo` runs only inside the paid window (from Thursday 29 October). It resolves each delisted company's final, often `Q`, ticker, checks the series' identity, and stores gzip files that are all registered for deletion.
   - `sentinel prices` builds one as-traded and adjusted series per issuer (`core.price_daily`) and the SPY session calendar.
2. **Reference data** (Step 7). `sentinel fetch-reference` and `sentinel reference` load the French library's factors, industries, SIC definitions and size breakpoints (through 2026-08-31), plus FINRA's tick-size pilot intervals.
3. **Company data** (Step 9). `sentinel fetch-company` downloads the SEC's two bulk archives (companyfacts 1.41 GB, submissions 1.57 GB) in 2 requests. `sentinel company-facts` extracts the universe's first-filed XBRL values, filing histories and current SIC.
4. **Final events** (Step 7). `sentinel detect`:
   - applies G8 to purchase lines, then finds candidates from 1 July 2011 (a six-month warm-up);
   - takes each candidate through cooldown → G7 → priced → floors;
   - keeps priced events and unpriced events, recording every outcome;
   - computes market caps and the coverage report.
   Missing signal-filing headers are fetched with `fetch-headers --final`.
5. **Delistings** (Step 8). `sentinel delistings` classifies every early-ending series from SEC filing evidence and assigns registered delisting returns and bounds.
6. **Costs** (Step 10). `sentinel costs` computes Abdi–Ranaldo spreads with the tick floor, 63-session volatility and the §6.8 cost, and writes `costs.md`.
7. **Checks**:
   - the golden set, delisting and market-cap sheets;
   - `sentinel coverage`;
   - W12–W25 invariants, including the truncation test;
   - `tiingo-status` and `tiingo-delete` for the deletion register.

There are no new dependencies (`yfinance` moves from the `mvp` group to the main ones). Research decisions are in [research.md](research.md) (R1–R18).

## Technical Context

**Language/Version**: Python 3.14.4, uv

**Primary Dependencies**: duckdb 1.5.x, pyarrow 25, httpx, typer, pyyaml, yfinance 1.7 (with pandas 3.0, already locked). No additions.

**Storage**:
- `data/warehouse.duckdb`: new tables in `core`, `evt` and `audit`; no new schemas.
- Raw files under `data/raw/`:
  - `yahoo/`
  - `tiingo/`: paid month only, registered for deletion
  - `french/`
  - `finra/`
  - `sec/company/`
  - `sec/headers/`
  Each file has a manifest line.
- Audit sheets and reports under `specs/004-market-data-events/`, committed. They hold no prices.

**Testing**:
- pytest offline. Fixtures are synthetic Yahoo frames and **synthetic** Tiingo CSVs (no real Tiingo data in the repository), plus small public excerpts from SEC, French and FINRA files.
- Builders take `cutoff` and `issuers` for truncation tests.
- Tests on the real warehouse are marked `slow`, and network tests `network`. Both run under the 5 GB ceiling.

**Target Platform**: Linux (WSL2), the researcher's workstation

**Project Type**: single-package CLI and data pipeline (extends `src/sentinel/`)

**Performance Goals**:

| Step | Expected time |
|---|---|
| Yahoo pull | about 10 min |
| Tiingo pull | under 1 hour (about 6,000 requests at 2 per second) |
| SEC bulk download | minutes |
| New build steps | about 20 min |
| Full offline rebuild of this feature's tables | under 30 min (SC-008) |

**Constraints**:
- **Memory**: under 5 GB peak; DuckDB at 3 GB and 4 threads; loading in chunked transactions.
- **Point in time**: no future data in any decision at T (W25).
- **Tiingo**: data written only inside the paid window and only to registered places.
- **SEC**: at most 10 requests per second.
- **No post-event return** is computed (constitution III).

**Scale/Scope**:
- About 6,450 priced issuers (3,671 Yahoo, 2,783 Tiingo) and 123 unmatched.
- About 18 M daily price rows.
- About 28,500 preliminary events from July 2011 (A 10,939, B1 4,804, B2 12,786) as the starting point.
- About 630 k clean-purchase lines for G8.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this feature complies | Status |
|---|---|---|
| **I. Point-in-Time Integrity** | Floors, spreads, volatility and market cap use rows up to the last session on or before T. G7 uses the signal filing's own header. XBRL values are first-filed on or before T. Entry is the session after T (W18). Price-level rules use as-traded prices (W15, the reverse-split test). The truncation test covers G8, candidates, outcomes, floors and market caps (W25; 20 real pairs). Current SIC is used only under the D45 fallback, which plan §11 pre-specifies, and each event records `g7_sic_source` | Pass |
| **II. Survivorship-Complete Data** | Delisted companies are priced from Tiingo. Unpriced events are kept, counted by year and group, and start cooldowns like priced ones. Every early-ending series gets a class from SEC filing evidence, never from a data gap alone, and an "unknown" class with bounds. Coverage is reported by year and delisting status, and the window never moves | Pass |
| **III. Pre-Registration and a Sealed Holdout** | Every threshold comes from `config/params.yaml`. The new rules (`rules.*`, the other-venue delisting return, D50) are added **before** `prereg-v1`. No returns, labels or outcomes are computed. Prices after T are stored for later features, but nothing measures post-event performance. Holdout-period events get floors and costs from data at or before T only | Pass |
| **IV. Honest Statistics and Economics** | Implements the §6.8 cost model, which every headline number will be net of. Gross figures are unaffected | Pass |
| **V. Reproducibility** | Raw files are immutable, with manifest lines (URL or library call, time, SHA-256). Builds are idempotent and deterministic (`exact_sum`, fixed seeds). The offline rebuild check runs and is logged before the paid month ends | Pass |
| **VI. Lawful, Low-Cost and Respectful Data Use** | **Tiingo**: a paid-window guard (exit 6), a deletion register covering raw files and every derived per-security table (with a completeness test), and a deletion command that rewrites the warehouse file. **SEC**: 2 bulk requests plus the existing header limiter. **Yahoo**: polite batches, personal use, no prices in any committed or published file. The French library is free for research, and FINRA is public | Pass |
| **VII. Simplicity and Scope Discipline** | Same stack, no new dependencies or schemas. Plotting is deferred to the report step: the cost report is a table. Labels, features and the event study stay out (later features) | Pass |

**Post-design re-check**: still passes.
- **New register value**: the only change to a registered value is the other-venue delisting return (D50). It covers a case the plan's §6.7 leaves open, and is decided before the lock.
- **Current SIC**: using the current SIC under `g7_no_sic = current_sic` is the plan's own §11 fallback.

## Project Structure

### Documentation (this feature)

```text
specs/004-market-data-events/
├── spec.md
├── plan.md                  # this file
├── research.md              # R1–R18: live checks and decisions
├── data-model.md            # new warehouse tables
├── quickstart.md            # end-to-end validation guide
├── contracts/
│   ├── cli.md               # new commands, exit code 6
│   ├── warehouse-schema.md  # W12 (revised) – W25
│   ├── params-rules.md      # params v8 additions
│   ├── audit-sheets.md      # golden set, delistings, market caps
│   └── tiingo-register.md   # what is registered and how it is deleted
├── audits/                  # generated sheets + researcher verdicts (committed)
├── coverage.md, costs.md    # generated reports (committed; aggregates only)
├── run-notes.md             # results of the real runs
├── checklists/requirements.md
└── tasks.md                 # /speckit-tasks
```

### Source Code (repository root)

```text
src/sentinel/
├── cli.py                    # + fetch-prices, fetch-reference, fetch-company, prices, reference,
│                             #   company-facts, detect, delistings, costs, coverage,
│                             #   audit golden|delistings|market-caps (+ summaries),
│                             #   tiingo-status, tiingo-delete; fetch-headers --final; build extended
├── config.py                 # Paths gains yahoo, tiingo, french, finra, sec_company, audits_004
├── warehouse.py              # check_invariants gains W12 (revised) – W24
├── ingest/
│   ├── yahoo.py              # yfinance batches → Parquet per ticker + manifest
│   ├── tiingo.py             # paid-window guard, list, resolution, identity, meta/prices → gzip
│   ├── french.py             # download + parse sectioned CSVs and Siccodes
│   ├── finra.py              # download + parse the pilot change file
│   └── sec_company.py        # stream the bulk zips; per-company JSON readers
├── core/
│   ├── prices.py             # stg.price_*, price_series, price_daily, session, price_issue
│   ├── reference.py          # ff_*, sic_industry, me_breakpoint, tick_pilot
│   ├── company.py            # issuer, company_filing, xbrl_fact (first-filed)
│   ├── delistings.py         # core.delisting
│   ├── tiingo_register.py    # TIINGO_DERIVED, status, delete (warehouse rewrite)
│   └── audit.py              # + golden set, delisting and market-cap sheets and summaries
└── events/
    ├── prelim.py             # find_events gains a `keep` (cooldown policy) argument
    ├── final.py              # G8, priced purchases, candidates → outcomes, evt.event, coverage
    └── costs.py              # Abdi–Ranaldo, Corwin–Schultz, volatility, cost, costs.md
tests/
├── unit/
│   ├── test_yahoo.py           # storage, as-traded rebuild, primary ticker
│   ├── test_tiingo.py          # guard (exit 6), resolution incl. Q, identity checks, gzip + manifest
│   ├── test_french.py          # sections, percent → decimal, −99.99, Siccodes ranges
│   ├── test_finra.py           # pilot intervals from change records
│   ├── test_sec_company.py     # first-filed rule, fallback tags, insider forms dropped
│   ├── test_prices.py          # series choice, Yahoo→Tiingo fallback, duplicates, calendar
│   ├── test_g8.py              # range ± tolerance, no_session, G6 re-applied, unpriced skip
│   ├── test_final_events.py    # G7 + D45 fallback, floors, cooldown in sessions, unpriced,
│   │                           #   Good Friday T, entry session, needs_header
│   ├── test_truncation_events.py
│   ├── test_delistings.py      # classes, windows, re-map, venue, returns, bounds
│   ├── test_costs.py           # AR recovery, tick floor incl. pilot, §6.8 illustration
│   ├── test_tiingo_register.py # completeness, deletion, W12
│   └── test_audit_004.py       # sheet layouts, seeds, summaries
├── integration/
│   ├── test_prices_real.py             # @slow: known reverse split, SPY calendar
│   ├── test_truncation_events_real.py  # @slow: 20 real (issuer, T) pairs
│   └── test_rebuild_identical.py       # @slow: offline rebuild = same tables
└── guards/                   # existing guards + "no real Tiingo data under tests/"
```

**Structure Decision**:
- **Placement**: modules follow plan §8.4. Fetchers go in `ingest`, warehouse layers in `core`, event logic in `events`.
- **Reuse**: final detection reuses feature 002's `find_events` through a new `keep` argument, and builds `core.priced_purchase` with the same aggregation as `core.clean_purchase`, so the A/B1/B2 rules exist in one place.
- **No MVP imports**: production code never imports `mvp/`. The yfinance download pattern is reimplemented in `ingest/yahoo.py`.

## Design Notes

- **Two runs before and after the Tiingo month.**
  - Everything except the Tiingo fetch is built and run on free data from 23 to 28 October. Tiingo issuers are simply unpriced until then.
  - On 29 October the Tiingo pull and one `build` complete the picture. The researcher's audits follow.
- **Build order**: `prices` → `reference` → `company-facts` → `detect` → `delistings` → `costs` (`detect` needs current SIC and XBRL; `delistings` needs the chosen series).
- **Large loads**:
  - Raw files go into `stg.price_*` in chunks of 250 tickers. Each chunk is one transaction into a shadow table, then swapped, as in feature 002's staging.
  - `core.price_daily` is one `create table as select`, which DuckDB streams.
  - Company zips are read one member at a time.
- **Shared cooldown code**: the session-based cooldown takes a predicate deciding which outcomes start a cooldown (`event`, `unpriced`). The floors-off coverage pass is the same code with floors disabled.
- **Headers**: `fetch-headers --final` reuses feature 002's fetcher with a different target list. Failures go to `core.header_failure`, and such candidates stay `needs_header` (reported).
- **Lock**: every build command fails clearly if `sentinel explore` holds the warehouse. The researcher closes it first.
- **What gets committed**: code, specs, audit sheets (no prices), `coverage.md` and `costs.md` (aggregates). Never `data/`.

## Schedule (Week 2)

| Date | Work |
|---|---|
| Fri 23 – Sat 24 Oct | params v8 + D50; `ingest/yahoo`, `french`, `finra`, `sec_company`; `prices`, `reference`, `company-facts` with tests; start the free downloads |
| Sun 25 – Mon 26 Oct | G8, `find_events(keep=…)`, final outcomes, floors, cooldown, coverage, market cap; truncation tests; `fetch-headers --final` |
| Tue 27 – Wed 28 Oct | `delistings`, `costs`; Tiingo module, register and deletion on synthetic data; full build on Yahoo-only data |
| Thu 29 Oct | **Researcher**: subscribe to Tiingo Power (auto-renew off), set `ops.tiingo_paid_until`, fill the D45 sheet → `rules.g7_no_sic`. Then the Tiingo pull, `build`, `coverage` |
| Fri 30 – Sat 31 Oct | **Researcher**: golden set, delisting and market-cap audits (about 2 h). Fixes |
| Sun 1 – Mon 2 Nov | Offline rebuild check (SC-008), real truncation test, run notes, merge to `main` |
| Tue 3 Nov | Feature complete. Wednesday 4 November: `prereg-v1` (Step 10a) |
| End of paid month (about 28 Nov) | `tiingo-delete --yes`, after the research that needs Tiingo data |

## Complexity Tracking

No constitution violations to justify.
