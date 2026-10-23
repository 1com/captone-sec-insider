# Data Model: Insider Warehouse

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Invariants**: [contracts/warehouse-schema.md](contracts/warehouse-schema.md)

The warehouse file is `data/warehouse.duckdb`. Column names are lower-case. CIKs are stored without zero padding. "Filing date" is the SEC filing date, the D of point-in-time rules.

## stg: typed copies of the SEC tables (Step 2)

One table per SEC table: `stg.submission`, `stg.reportingowner`, `stg.nonderiv_trans`, `stg.nonderiv_holding`, `stg.deriv_trans`, `stg.deriv_holding`, `stg.footnotes`, `stg.owner_signature`.

| Rule | Detail |
|---|---|
| Columns | The SEC columns, lower-cased, plus `quarter` (e.g. `2019q1`) and `src_row` (1-based data-row number in the file) |
| Types | `*_date` columns → DATE (`DD-MON-YYYY`); shares, prices and values → DOUBLE; the flags listed in research R2 → BOOLEAN; CIKs → VARCHAR without padding; everything else → VARCHAR |
| Drift | `submission.aff10b5one` is null before 2023 Q1 |
| Key | (`quarter`, `src_row`) is unique in every table. Duplicates across quarters are kept here and resolved in `core` |
| Row check | Count per (table, quarter) = data-row count of the source file (SC-001) |

**`stg.conversion_issue`**: (`table_name`, `quarter`, `src_row`, `column_name`, `raw_value`). There is one row per non-empty value that failed to convert.

**`stg.load_report`**: (`table_name`, `quarter`, `rows_expected`, `rows_loaded`, `columns`), which is also the source of the drift report.

## core: production insider layers

### `core.filing` (Step 2/3 helper)

One row per accession, deduplicated as the first occurrence by quarter: `accession` (PK), `quarter`, `filing_date`, `document_type`, `issuer_cik`, `issuer_name`, `symbol_raw`, `aff10b5one`.

### `core.entity_member` (Step 3)

| Column | Meaning |
|---|---|
| `issuer_cik`, `owner_cik` | The owner at this issuer |
| `entity_id` | `"{issuer_cik}:{min owner CIK in the component}"` at `valid_from` |
| `valid_from` | Filing date of the filing that created or changed the membership |

- **Key**: (`issuer_cik`, `owner_cik`, `valid_from`).
- **Lookup**: the entity at T is the row with the greatest `valid_from ≤ T`. An owner with no row before T has not yet filed for that issuer.
- **Monotonic**: an owner's component only grows, so all owners sharing an `entity_id` at T stay together after T.

### `core.owner_role` (Step 3)

| Column | Meaning |
|---|---|
| `issuer_cik`, `owner_cik`, `valid_from` | Interval start, the filing date of the first filing with this role |
| `role` | `ceo_cfo` / `officer` / `director` / `ten_pct` / `other` |
| `seniority` | 4 / 3 / 2 / 1 / 0 |
| `is_director`, `is_officer`, `is_ten_pct`, `is_other`, `title` | From that filing |

- **Key**: (`issuer_cik`, `owner_cik`, `valid_from`).
- **Owner role at T**: the latest interval with `valid_from ≤ T`.
- **Entity role at T**: the maximum `seniority` over the members of its `entity_id` at T.

### `core.transaction` (Step 4)

One row per non-derivative transaction line of any form.

| Column | Meaning |
|---|---|
| `accession`, `line_sk` | PK, deduplicated as the first quarter |
| `quarter`, `issuer_cik`, `filing_date`, `document_type` | From `core.filing` |
| `security_title`, `trans_date`, `trans_code`, `acq_disp`, `shares`, `price`, `shares_after`, `direct_indirect`, `nature_of_ownership` | Typed from staging |
| `fn_ids` | VARCHAR[], the footnote IDs cited by any `*_fn` column of the line |
| `value_usd` | `shares × price`, null if either is missing |
| `g1_form4`, `g2_purchase`, `g3_common`, `g4a_no_checkbox`, `g4b_no_plan_fn`, `g5_no_offering_fn`, `g6a_timely_valued` | Gate flags in order (research R5) |
| `passes_lines` | All seven line gates |

### `core.clean_purchase` (Step 4)

One row per entity per filing. Co-filers are one entity, so this is one row per filing that passes.

| Column | Meaning |
|---|---|
| `accession` | PK |
| `issuer_cik`, `filing_date`, `quarter` | |
| `entity_id`, `entity_role`, `entity_seniority` | As of `filing_date` (ASOF) |
| `owner_ciks` | VARCHAR[], sorted |
| `value_usd`, `shares` | Sums over passing lines. Must satisfy `value_usd ≥ g6_min_value` |
| `max_trade_date`, `min_trade_date` | Trade dates of the passing lines |
| `shares_before`, `shares_after` | Summed over the entity's common-stock holdings in the filing (research R5); null if not computable |
| `opens_position` | `shares_before = 0` |

### `audit.funnel` (Step 4)

(`quarter`, `step`, `gate`, `unit`, `rows_in`, `rows_out`, `rows_removed`).
- `unit = lines` for the seven line gates; `unit = filings` for G6b.
- `rows_in = rows_out + rows_removed`, and line gates chain: step k's `rows_in` = step k−1's `rows_out`.

## evt: preliminary events (Step 5)

### `evt.prelim_event`

| Column | Meaning |
|---|---|
| `event_id` | PK, `"{issuer_cik}:{group}:{signal_date}"` |
| `issuer_cik`, `group` (`A` / `B1` / `B2`), `signal_date` | T = filing date of the completing filing |
| `signal_accession` | The latest-filed member filing on T (highest accession on T) |
| `n_entities`, `total_value_usd`, `max_seniority` | Over the window, with entities and roles as of T |
| `in_labelled_window` | `signal_date ≥ registered.labelled_window_start` |
| `passes_price_standin` | Comparison only: every member line has price ≥ $2 (SC-005 variant) |

**Rules**:
- **Window**: [T − (`cluster_window` − 1), T].
- **A**: `n_entities ≥ 2`, with at least one entity of seniority ≥ 2, and `total ≥ cluster_min_value`.
- **B1**: one entity with seniority 4.
- **B2**: one entity with seniority 2 or 3.
- **Cooldown**: `rules.prelim_cooldown_calendar_days` per issuer and per group.

### `evt.prelim_event_member`

(`event_id`, `accession`, `entity_id_at_t`, `entity_role_at_t`, `value_usd`).

## Symbols and headers (Step 6)

### `core.symbol_map`

| Column | Meaning |
|---|---|
| `issuer_cik`, `ticker`, `valid_from`, `valid_to` | Ticker normalised. Dates are inclusive; `valid_to` is null when the ticker is still current |
| `price_source` | `yahoo` / `tiingo` |
| `match_quality` | `sec_current` / `sec_current_otc` / `form4_history` |

- **Key**: (`issuer_cik`, `ticker`, `valid_from`).
- **Content**: SEC-derived tickers only (constitution VI).

### `core.symbol_unmatched`

(`issuer_cik`, `issuer_name`, `reason`), where `reason` is `no_ticker` or `fund_like`.

### `core.filing_header`

| Column | Meaning |
|---|---|
| `accession` | PK |
| `issuer_cik` | |
| `form_type`, `filed_as_of` | From the header |
| `accepted_at_et` | TIMESTAMP, `ACCEPTANCE-DATETIME` as US Eastern time |
| `sic`, `sic_label` | From the `<ISSUER>` block; null if absent |
| `raw_path` | Path under `data/raw/` |

### `core.header_failure`

(`accession`, `reason`, `last_attempt`).

## Build log

**`core.build_log`**: (`step`, `started_at`, `finished_at`, `input_fingerprint`, `rows_written`).
