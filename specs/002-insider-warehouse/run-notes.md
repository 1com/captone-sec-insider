# Run Notes: Feature 002

Results of the real runs (tasks T013, T024, …).

## T013: Staging (2026-10-23)

| Check | Result | Criterion |
|---|---|---|
| `sentinel stage` | 37,937,561 rows, 8 tables × 83 quarters, exit 0, in **4 min 12 s** (250 s for the step) | — |
| Rows loaded vs data rows in the files | 37,937,561 = 37,937,561, **0 mismatches** over 664 (table, quarter) pairs | SC-001 ✅ |
| Conversion issues | **0**: every non-empty date, number and flag converted | FR-002 ✅ |
| Column drift | only `submission.aff10b5one`, present in 15 quarters (2023q1–2026q3) | research R1 ✅ |
| Null `rptownercik`, `filing_date` or `issuercik` | 0, 0, 0 | — |
| Peak memory (systemd cgroup, RAM + file cache) | 4.9 GB | — |
| Warehouse file | `data/warehouse.duckdb`, 2.3 GB | — |

| Table | Rows |
|---|---|
| `footnotes` | 9,493,188 |
| `nonderiv_trans` | 7,353,719 |
| `reportingowner` | 4,874,337 |
| `owner_signature` | 4,793,015 |
| `submission` | 4,496,561 |
| `deriv_trans` | 2,757,824 |
| `nonderiv_holding` | 2,407,604 |
| `deriv_holding` | 1,761,313 |

### Memory: why staging commits per quarter

The first design loaded all 83 quarters in **one transaction**. Four attempts on 22–23 October were cut off before finishing, after 15–28 minutes and at most 20 quarters. The later ones went down together with VS Code's WSL session (a 10 GB VM, of which the editor uses 4–5 GB). A fifth attempt, under a 5 GB cgroup cap, stalled at 20 quarters with its memory full. A probe on the first 12 quarters showed why: DuckDB holds uncommitted rows in memory (`IN_MEMORY_TABLE` in `duckdb_memory()`, none spilled to disk), and the process grew by about **300 MB per quarter** (4.3 GB after 12 quarters). Committing each quarter kept the process flat at about 2 GB.

- **Change**: `stage_all` now loads each quarter in its own transaction into shadow tables (`stg._new_*`). One final transaction drops the old tables and renames the shadow ones into place, so a failed run still leaves the previous tables untouched (`test_a_failed_rebuild_keeps_the_previous_tables`).
- **Also**: `warehouse.connect` caps DuckDB at 3 GB (the default is 80% of RAM). Heavy steps run as `systemd-run --user -p MemoryMax=5G -p MemorySwapMax=1G …`, so a runaway step is killed on its own instead of taking down the VM.

### Relationship values (input to Step 3)

Until 2022 the SEC files glue `Other` to the previous flag without a comma: `TenPercentOwnerOther` (36,764 rows), `DirectorOther` (16,997), `OfficerOther` (10,145), `Director,TenPercentOwnerOther`, and so on. From 2023q1 they are comma-separated (`Director,Other`). Splitting on commas would have demoted these owners to `other`. Roles therefore match each flag as a substring, since no flag name contains another. 503 owner rows have no relationship and get role `other`.

## T024 (part 1): Entities (2026-10-23)

| Check | Result | Criterion |
|---|---|---|
| `sentinel entities` | 5,508,835 rows written, exit 0, in **17 s**; peak memory 2.7 GB | — |
| `core.filing` | 4,496,561 filings (no accession appears in two quarters) | W3 ✅ |
| `core.entity_member` | 470,278 (issuer, owner) pairs, 477,714 rows | — |
| Entities at the end of the history | 409,508, of which **15,872** have several owners | — |
| `core.owner_role` | 534,560 intervals; 45,234 owners change role at least once | — |
| W7 (monotonic) and W8 (one entity per filing) | 0 violations each | ✅ |

- **Entity sizes**: 393,636 single owners, 4,581 pairs and 2,971 triples. The largest are private-equity families filing jointly, e.g. 54 Blackstone vehicles at Invitation Homes (`1687229:1070844`), which together count as one buyer, as intended (research R3). There is no runaway component.
- **Latest role per owner**: director 170,908; officer 133,262; ten_pct 73,235; ceo_cfo 54,219; other 38,654.

## T024 (part 2): Gates (2026-10-23, G6 minimum $25,000 per D46)

| Check | Result | Criterion |
|---|---|---|
| `sentinel gates` | 7,515,442 rows written, exit 0, in **27 s**; peak memory 4.5 GB (RAM + file cache) | — |
| Clean purchases | **161,059** filings (median $109,710) | SC-002 |
| Funnel | reconciles in every quarter | W5 ✅ |
| Clean purchases below $25,000 | 0 | W6 ✅ |
| Duplicate keys (`accession`; `accession`, `line_sk`) | 0; 0 | W3 ✅ |
| Holdings not computable | before 2,016 (1.3%), after 142 | — |

| Gate | Lines in | Lines out |
|---|---|---|
| G1 original Form 4 | 7,353,719 | 7,072,161 |
| G2 open-market purchase (code P, acquired) | 7,072,161 | 818,363 |
| G3 common stock | 818,363 | 779,482 |
| G4a 10b5-1 checkbox not ticked | 779,482 | 774,980 |
| G4b no cited plan footnote | 774,980 | 689,376 |
| G5 no cited offering footnote | 689,376 | 680,885 |
| G6a filed within 30 days, valued | 680,885 | 630,630 |
| **G6b ≥ $25,000 per filing** (filings) | 318,545 | **161,059** |

- **Against feature 001**: every one of the 143,995 provisional clean filings of at least $25k is also a production clean purchase. Production has 17,064 more because it drops the provisional $2 transaction-price stand-in (research R5: price floors use market prices in feature 003). With that stand-in re-applied to every line, production has 143,709 (−0.2%).
- **Entity role at the filing date**: director 69,758; ten_pct 34,720; ceo_cfo 31,344; officer 21,038; other 4,199; none missing.
- **New positions** (`opens_position`): 13,196 (8%).
- **Per year**: 5,645–9,164 a year, except 2007 (11,971) and 2008 (14,606). 2026 covers Q1–Q3 only (4,763).

## T024 (part 3): Audit sheets (2026-10-23)

`sentinel audit sheets` (seed 2002, 4 s) wrote `audits/entities.csv`, `audits/gates_excluded.csv` and `audits/gates_kept.csv`, 50 rows each. The excluded sheet has 10 rows per deciding gate: G3, G4 (8 × G4b, 2 × G4a), G5, G6a and G6b. **Verdicts are pending with the researcher**; `sentinel audit summary` scores them (SC-004: at least 90% agreement per sheet).

Seen while checking the sheets, before any verdicts:
- **Likely G3 error**: Analog Devices' "Comm Stock - $.16-2/3 value" is common stock, but `gate_common_title_regex` needs the word "common". Expect abbreviations of this kind among the G3 exclusions.
- **Judgment case**: master limited partnerships' "Common units representing limited partner interests" fail G3 on `\bunits?\b`, which is meant for SPAC units.
- **Quoting, cosmetic only**: about 1.0 M of 9.5 M footnotes, and 6,165 security titles, keep the SEC files' CSV-style quoting (`"…(""Common Units"")…"`), because the TSV reader runs with quoting off so that row counts match the files exactly. The gate regexes match substrings, so no decision changes.

## T031: Preliminary events and the comparison (2026-10-23)

| Check | Result | Criterion |
|---|---|---|
| `sentinel detect-prelim` | 39,498 events with 70,831 member purchases, exit 0, in **20 s** | — |
| A / B1 / B2 | 15,391 / 6,498 / 17,609; in the labelled window (from 2012) 10,401 / 4,602 / 12,287 | — |
| Issuers with an event | 8,527 (6,373 in the labelled window): the symbols to map and price | — |
| Event IDs unique; every event has members and a signal filing | yes | W3 ✅ |
| A under production + $2 | **13,731** ≤ feature 001's 16,513 | SC-005 ✅ |
| Gap to feature 001 with its rules restored (+ $2, − O/D, G6 $10k) | A −1.2%, B1 +0.1%; no year above 15% | SC-005 ✅ |
| History check (W9) | events up to each cutoff are identical between cutoff and full builds | ✅ |

`sentinel compare-provisional` writes `comparison.md`, with the per-year tables and the explanations of what each rule changes. Feature 001's provisional events were built at the pilot's G6 of $10k, now `provisional.filing_min_value`. The comparison isolates D46 with its own column.

## T037 (part 1): Symbol map (2026-10-23)

| Check | Result | Criterion |
|---|---|---|
| `sentinel symbols --tiingo-report` | 28,521 ticker rows and 2,016 unmatched issuers, from the SEC snapshot of 22 Oct; 1 s | — |
| Event companies mapped | **8,361 of 8,527 (98.1%)**: Yahoo 3,824, Tiingo 4,537; unmatched 166 (fund_like 73, no_ticker 93) | SC-006 ≥ 95% ✅ |
| Every event company mapped or listed; SEC tickers only | 0 problems | W10, W11 ✅ |
| Tiingo's public list (Last-Modified 23 Oct 10:05 GMT), held in memory | all delisted event companies: 2,790 of 4,537 matched (135 via a `Q` ticker), 631 ticker only, 1,116 unmatched | — |
| … delisted companies with A or B1 events from 2012 | **1,748 of 2,073 matched (84%)**, 115 ticker only, 210 unmatched; feature 001 found 83% for a 2016 start | — |

A and B1 events from 2012: 15,003, of which 9,710 are at companies listed today (Yahoo) and 5,077 at delisted ones. If the matched delisted companies price, coverage is about 93% before G7, which removes many of the unmatched funds (target ≥ 90%, Step 7).

The first run ran out of memory: `list(issuer_name order by …)[1]` built one list per issuer over 4.5 M filings. `arg_max` keyed on date and accession gives the same name.

## T037 (part 2): Filing headers (pending)

On 23 Oct EDGAR answered uncached pages with HTTP 503, "SEC.gov is undergoing maintenance". A 20-header smoke test stored 9, which parse correctly (e.g. CIK 2488 SIC 3674; CIK 2230 no SIC). A background job retries every 10 minutes and then runs the full fetch of about 27,300 headers, one request at a time (about 0.6 s each when EDGAR is healthy).

## T038–T040, T043: Invariants, history test on real data, full rebuild (2026-10-23)

| Check | Result | Criterion |
|---|---|---|
| `sentinel build` from `data/raw/` (warehouse set aside first) | **6 min 2 s** (stage 288 s, entities 18 s, gates 28 s, events 21 s, symbols 1 s, headers 2 s, invariants 4 s); peak 5.1 GB including file cache, under a 5 GB cgroup ceiling | SC-008 < 30 min ✅ |
| `check_invariants` (W1–W8, W10, W11) after the rebuild | all hold | ✅ |
| History test on real data: 20 (issuer, T) pairs, seed 2002, issuers with ≥ 5 clean purchases and a co-filing merge; entities, roles, clean purchases and events rebuilt from filings ≤ T | **20 of 20 identical** to the full build at ≤ T | W9, SC-003 ✅ |
| Rebuilt against the previous warehouse | identical counts in every table; identical entities, roles, symbol map and events (ids, groups, entities, signal filings) | Determinism ✅ |
| `ruff check`, `ruff format --check`, `pytest` (offline), `pytest -m slow` | clean, clean, 205 passed (1 network test skipped), 21 passed | ✅ |
| `find data -iname '*tiingo*'` | empty | W12 ✅ |

**Order-dependent sums, found by the history test.** The first run failed 5 of 20 pairs on `core.clean_purchase`: totals such as `133916.40000000002` against `133916.4`, a different pair on each run. DuckDB adds rows in parallel, in an order that changes between runs, and floating-point addition depends on order. Every SQL sum of values and shares (gates, events, comparison) now goes through `warehouse.exact_sum`: each term is rounded to 1e-8 and added as DECIMAL, so rebuilds are identical. Effects against the previous build: 23 clean purchases changed value by more than 1e-6, all of them over $1 billion (the largest $0.50), and 5 purchases whose "before" holdings were a floating-point −1e-10 (nulled as negative) now compute as 0. Holdings not computable: before 2,011 (was 2,016), after 142.

**Memory.** The first slow-test run opened its scratch databases without the 3 GB DuckDB cap (default: 80% of RAM, 16 threads) and was killed by the kernel. Scratch databases now take `warehouse.MEMORY_LIMIT` and 4 threads, and slow tests run under the same cgroup ceiling as the build steps.

**Quickstart.** Every step has been run on the real data except `sentinel verify-sec` for the headers, which follows the full header fetch, and `audit summary`, which waits for the researcher's verdicts (T041).
