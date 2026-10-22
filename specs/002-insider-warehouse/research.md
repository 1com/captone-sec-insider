# Research: Insider Warehouse

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-22

Live checks run on 2026-10-22 against the 83 stored archives and one EDGAR header. Feature 001's findings (TSV format, quoting off, footnote ID lists, `DD-MON-YYYY` dates, CIK padding) carry over: see [../001-skeleton-sec-ingest/research.md](../001-skeleton-sec-ingest/research.md) R2–R3.

## R1. Size and drift of the staging input

- **Finding**: 8 tables, **37,937,561 data rows**, 5.61 GB of text across 83 quarters. A newline count of all archives takes 17 s.

  | Table | Rows | Text size |
  |---|---|---|
  | FOOTNOTES | 9,493,188 | 2.39 GB |
  | NONDERIV_TRANS | 7,353,719 | 0.82 GB |
  | REPORTINGOWNER | 4,874,337 | 0.68 GB |
  | OWNER_SIGNATURE | 4,793,015 | 0.37 GB |
  | SUBMISSION | 4,496,561 | 0.48 GB |
  | DERIV_TRANS | 2,757,824 | 0.46 GB |
  | NONDERIV_HOLDING | 2,407,604 | 0.19 GB |
  | DERIV_HOLDING | 1,761,313 | 0.23 GB |

- **Drift**: one column only. `SUBMISSION.AFF10B5ONE` appears from **2023 Q1** (15 quarters). Every other table has identical columns in all 83 quarters.
- **Decision**: stage each table as a typed DuckDB table in schema `stg`, columns lower-cased with the SEC names otherwise kept. Add `quarter`, plus `src_row`, the 1-based row number in the source file, so every staged row traces back to its file. `aff10b5one` is null before 2023.
- **Row-count check (FR-004, SC-001)**: the expected count is the file's newline count minus the header. This equals the parsed row count because no field contains a newline (feature 001 R2).

## R2. Typing without losing text (FR-002)

- **Decision**: cast as follows:
  - dates with `try_strptime(…, '%d-%b-%Y')`;
  - numbers with `try_cast(… AS DOUBLE)`;
  - the flag columns (`EQUITY_SWAP_INVOLVED`, `AFF10B5ONE`, `NO_SECURITIES_OWNED`, `NOT_SUBJECT_SEC16`, `FORM3_HOLDINGS_REPORTED`, `FORM4_TRANS_REPORTED`) to booleans from `0/1/true/false`.

  A non-empty value that fails to convert is written to **`stg.conversion_issue`** (table, quarter, `src_row`, column, raw text), and the typed column holds null.
- **Rationale**: keeping a raw text twin of every typed column would roughly double 38 M rows. Failures are rare, under 1% of prices (R5), so a side table preserves the original text at almost no cost and gives the per-column failure counts directly.
- **Alternative rejected**: all-text staging with typing in `core`. Every later query would repeat the casts.

## R3. Point-in-time entities (FR-006, FR-008)

- **Decision**:
  - Per issuer, process all filings of any form (3, 4, 5 and amendments) in filing-date order with an incremental union-find over the owner CIKs on each filing. Owners on one filing are unioned.
  - After each filing **date** (all same-day filings together, because "dated on or before T" includes T), every owner whose component changed gets a new membership row: (`issuer_cik`, `owner_cik`, `entity_id`, `valid_from`).
  - `entity_id` = `issuer_cik:min(owner CIK in the component)` at that date.
  - The entity of an owner at date T is the latest row with `valid_from ≤ T` (an ASOF lookup).
- **Rationale**: components only ever merge, so the full history is a short list of merge events per issuer. One pass over about 4.5 M filings with about 4.9 M owner rows takes about a minute in Python. Pure SQL connected components would need iterative label propagation.
- **Consequence**: all owners on one filing are one entity from that date, so "per entity per filing" (G6) equals the filing total (spec Assumptions).
- **Events use entities as of T**, not as of each purchase. Two purchases by owners who merge before T count as one entity at T, which is what the truncation test checks.

## R4. Roles (FR-007)

- **Decision**:
  - **Owner role at T** comes from the owner's *latest* filing for that issuer dated on or before T. Flags come from `RPTOWNER_RELATIONSHIP` (`Director`, `Officer`, `TenPercentOwner`, `Other`, comma-separated). CEO/CFO is decided by `Officer` plus the title matching `rules.role_ceo_cfo_title_regex`, which starts from feature 001's regex.
  - **Seniority**: CEO/CFO = 4, other officer = 3, director = 2, 10% owner = 1, other = 0. An owner with several flags takes the highest.
  - **Storage**: consecutive filings with the same role collapse into intervals, `core.owner_role` (`issuer_cik`, `owner_cik`, `valid_from`, role, flags, title).
  - **Entity role at T** = maximum seniority over the entity's members at T.
- **Rationale**: "role taken from its filings dated on or before T" (plan §6.3). Using the latest filing handles promotions (director → CEO) and departures (CEO → director) with one rule. Window functions in DuckDB handle about 4.9 M rows in seconds.

## R5. Gates, valuation and holdings (FR-009 – FR-013)

- **`core.transaction`**: every **non-derivative** transaction line of every form, deduplicated by (`accession`, `nonderiv_trans_sk`), keeping the first quarter as feature 001 did. Derivative lines stay in `stg` for the future product lookup. The selling features (F12, F13) need only non-derivative code S lines.
- **Gate order** (line level), with flags in `core.transaction`:
  1. G1 `document_type = '4'`;
  2. G2 `trans_code = 'P'` and `acq_disp = 'A'`;
  3. G3 security title matches `rules.gate_common_title_regex` and not `rules.gate_excluded_title_regex`;
  4. G4a checkbox not ticked;
  5. G4b no cited footnote matching `rules.gate_plan_footnote_regex`;
  6. G5 no cited footnote matching `rules.gate_offering_footnote_regex`;
  7. G6a `0 ≤ filing_date − trans_date ≤ g6_timeliness` and a positive valued amount (shares × price);
  8. filing level: G6b total ≥ `g6_min_value`.
- **No transaction-price floor.** That was feature 001's stand-in. Price floors use market prices in feature 003, so the preliminary event set is a superset, which is right for choosing what to price. The comparison report (R8) also shows counts with the $2 stand-in, for a like-for-like check (SC-005).
- **Coverage on purchase lines (2012 Q2 / 2019 Q1 / 2025 Q2)**: `SHRS_OWND_FOLWNG_TRANS` is present on ≥ 99.9%. Holdings are **direct on 68% / 37% / 63%** of lines and **indirect** (trusts, funds, family) **on 32% / 63% / 37%**. Price is missing on ≤ 0.7%.
- **Holdings before and after (F7)**: within the filing, group the entity's common-stock lines by holding (`direct_indirect`, `nature_of_ownership`).
  - **After** = the holding's `shrs_ownd_folwng_trans` on its last line (highest `nonderiv_trans_sk`).
  - **Before** = after − Σ shares acquired + Σ shares disposed on that holding in the filing.
  - Common-stock rows in `NONDERIV_HOLDING` for the same filing, which hold shares that were not traded, add the same amount to both before and after.
  - The holdings are then summed. A negative "before" (data errors) is set to null and counted.
- **Funnel**: as in feature 001. Eight line-level gates in sequence, then one filing-level row (G6b), in `audit.funnel`.

## R6. Preliminary events (FR-014, FR-015)

- **Decision**: per issuer, at each distinct clean-purchase filing date T, take the window [T − (`cluster_window` − 1), T] and map every purchase to its owner's **entity at T** (R3), with the **entity role at T** (R4).
  - **A**: at least 2 entities, at least one with role ≥ director (2), total ≥ `cluster_min_value`.
  - **B1**: exactly one entity, with role CEO/CFO, total ≥ `cluster_min_value`.
  - **B2**: exactly one entity, with role other officer (3) or director (2), total ≥ `cluster_min_value`.
  - **Cooldown**: `rules.prelim_cooldown_calendar_days` (91) per issuer and per group, started only by events.
  - **Storage**: `evt.prelim_event` and `evt.prelim_event_member`, kept separate from feature 003's `evt.event`.
- **Scope**: all years from 2006, because cooldowns before 2012 affect 2012 and the comparison spans 2006–2026.

## R7. Symbol map (FR-017 – FR-019)

- **Decision**: build `core.symbol_map` (`issuer_cik`, `ticker`, `valid_from`, `valid_to`, `price_source`, `match_quality`) from:
  1. **Listed**: the CIK is in the latest SEC ticker snapshot. Each current ticker gets `price_source = yahoo`, with `match_quality = sec_current` for an exchange listing or `sec_current_otc` when the snapshot lists the CIK only as OTC or with no exchange. Yahoo usually holds a renamed company's full history under the current ticker. OTC-now companies are flagged so feature 003 can fall back to Tiingo if Yahoo's history is short.
  2. **Delisted**: each normalised `ISSUERTRADINGSYMBOL` in the company's filings, valid from its first to its last filing date, with `price_source = tiingo` and `match_quality = form4_history`. Normalisation follows feature 001's `normalise()`, which moves to a shared module because production code cannot import `sentinel.provisional`.
  3. **Unmatched**: no ticker in any filing and not in the snapshot. The company goes to `core.symbol_unmatched` with a reason (`no_ticker`, or `fund_like` when the name or ticker suggests a non-traded fund).
- **Tiingo**: the stored map holds SEC-derived tickers only (constitution VI). The run *reports* how many delisted event companies resolve against Tiingo's public list, including `Q` and OTC tickers, computed in memory with feature 001's matching logic, which moves to a shared non-provisional module. Feature 003 stores the resolved Tiingo tickers once the paid month starts.

## R8. Comparison with the provisional events (FR-016, SC-005)

- **Decision**: `sentinel compare-provisional` reads `data/provisional/events_PROVISIONAL.parquet` as a file, without importing `sentinel.provisional`. It writes `specs/002-insider-warehouse/comparison.md` with A, B1 and B2 counts per year, provisional against production, in three variants that attribute the differences:
  1. **production**, the full rules;
  2. **production + $2 stand-in**, the like-for-like comparison for SC-005;
  3. **production + $2 stand-in − officer/director condition**, which isolates that rule. The remaining gap is attributed to entity merging and per-filing valuation.

## R9. Filing headers (FR-020, FR-021)

- **Finding**: `https://www.sec.gov/Archives/edgar/data/{issuer_cik}/{accession without dashes}/{accession}-index-headers.html` returns about 2.7 KB of SGML-like text. Example for Air Products, filed 2019-07-26:
  - `ACCEPTANCE-DATETIME>20190726114841`;
  - `FILED AS OF DATE: 20190726`;
  - in the `<ISSUER>` block, `STANDARD INDUSTRIAL CLASSIFICATION: INDUSTRIAL INORGANIC CHEMICALS [2810]`.

  The `<REPORTING-OWNER>` block has no SIC.
- **Decision**:
  - **Which filings**: only the signal filings of preliminary events with T ≥ 2012-01-01, because G7 applies to labelled and holdout events only. Estimate: about 20,000 including B2.
  - **Storage**: raw files at `data/raw/sec/headers/{yyyy}/{accession}.txt`, read-only, with manifest source `sec_filing_header`.
  - **Parsing**: SIC is the four digits in brackets inside the `<ISSUER>` block. Acceptance time is the `ACCEPTANCE-DATETIME` value, interpreted as US Eastern time. Results go to `core.filing_header` (`accession`, `issuer_cik`, `sic`, `sic_label`, `accepted_at_et`, `filed_as_of`, `form_type`). A missing SIC is recorded as null, not as a failure, because some filers have none.
  - **Rate**: target **8 requests per second** (new `ops.sec_header_target_requests_per_second`, below the ceiling of 10), so about 40 minutes, run in the background. It is resumable: headers already stored are skipped.
- **Manifest at scale**: feature 001's `append()` re-reads the whole manifest on every call, which is O(n²) for 20,000 appends. **Decision**: add a `Manifest` class that loads the index once and appends with flush + fsync per line. `append()` keeps its behaviour for existing callers.

## R10. Truncation test on real data (FR-023, SC-003)

- **Decision**: every core builder takes an optional `cutoff` date and an optional issuer list. The test picks 20 (issuer, T) pairs with a fixed seed from issuers with at least 5 clean purchases and at least one co-filing merge, rebuilds entities, roles, clean purchases and preliminary events for those issuers from records with `filing_date ≤ T`, and checks that everything dated on or before T matches the full build. Synthetic cases cover late merges, same-day filings and promotions.
- It is marked `slow`, runs against the real warehouse, and is skipped when the warehouse is absent so the offline unit suite stays fast.

## R11. Audit sheets (FR-025, SC-004)

- **Decision**: `sentinel audit sheets` writes three CSVs to `specs/002-insider-warehouse/audits/` with a fixed seed:
  - `entities.csv`: 50 random multi-member entities with members, roles and the linking filings;
  - `gates_excluded.csv`: 50 random purchase lines excluded by G3–G6, stratified by gate, with the deciding gate and the cited footnote text;
  - `gates_kept.csv`: 50 random clean purchases.

  Each row has an EDGAR filing-index link (`https://www.sec.gov/Archives/edgar/data/{cik}/{acc-nodash}/`) and empty `verdict` (`correct` / `wrong` / `unclear`) and `notes` columns. `sentinel audit summary` computes agreement rates for the run notes. The sheets hold public SEC data only, so they are committed with the feature.

## R12. Parameter file additions

- **Decision**: a new section **`rules`**, holding research rules that are not numeric Appendix E rows but that `prereg-v1` must lock:
  - `gate_common_title_regex`, `gate_excluded_title_regex`, `gate_plan_footnote_regex`, `gate_offering_footnote_regex`, `role_ceo_cfo_title_regex` (initial values copied from `provisional`);
  - `prelim_cooldown_calendar_days: 91`.

  Keys are prefixed because `load_params` rejects a key that appears in two sections. `config.SECTIONS` and `check_register` gain `rules`, and the params contract is updated.
- **Also**: `ops.sec_header_target_requests_per_second: 8` and `ops.sec_headers_url_pattern`.

## R13. Libraries

No new dependencies. DuckDB 1.5 provides ASOF joins and window functions. pyarrow already streams the TSVs (`sentinel.ingest.sec_tables`).
