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
