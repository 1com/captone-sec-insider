# Data Model: Market Data, Final Events, Delistings, Company Financials and Trading Costs

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Invariants**: [contracts/warehouse-schema.md](contracts/warehouse-schema.md)

These tables extend `data/warehouse.duckdb` (feature 002's conventions still hold: lower-case columns, CIKs without zero padding). A **session** is a trading day in `core.session`. "As-traded" means the price or volume actually printed that day. "Adjusted" means split- and dividend-adjusted. Every table that can hold a value derived from Tiingo prices has a `price_source` column and is listed in the Tiingo register (research R15).

## Prices (Step 7)

### `stg.price_yahoo`

Typed rows of the stored Yahoo Parquet files.

| Column | Meaning |
|---|---|
| `ticker`, `session` | Yahoo ticker and date |
| `open`, `high`, `low`, `close`, `volume` | As Yahoo gives them: **split-adjusted** |
| `adj_close` | Split- and dividend-adjusted |
| `dividend`, `split_ratio` | Event on that date (`split_ratio` 1 when none; 2 for a 2-for-1 split, 0.1 for 1-for-10) |
| `raw_path` | Source file |

- **Key**: (`ticker`, `session`), after the duplicate rule (research R4).

### `stg.price_tiingo`

Same layout for the Tiingo CSVs: raw `open`, `high`, `low`, `close`, `volume`; `adj_open`, `adj_high`, `adj_low`, `adj_close`, `adj_volume`; `dividend`, `split_ratio` (Tiingo `splitFactor`); `raw_path`. The values here are as-traded. `price_source` is always `tiingo`, and the whole table is registered for deletion.

### `core.tiingo_listing`

During the paid month only: Tiingo's list rows (ticker, exchange, asset type, start, end) for the tickers this feature tried, plus the meta response (name, exchange code, start, end). The whole table is registered for deletion.

### `core.price_series`

| Column | Meaning |
|---|---|
| `issuer_cik`, `price_source`, `ticker` | One candidate series |
| `role` | `primary` / `fill_in` / `other_class` / `fallback` |
| `first_session`, `last_session`, `n_sessions` | From the provider rows |
| `identity` | `ok` / `dates` / `name` / `no_data` / `not_checked` (Yahoo, current tickers) |
| `chosen` | TRUE for the series that feeds `core.price_daily` (the primary plus its fill-ins) |
| `reason` | Why chosen or not, e.g. `yahoo_primary`, `tiingo_resolved`, `yahoo_starts_late→tiingo` |

- **Key**: (`issuer_cik`, `price_source`, `ticker`).
- **Rule**: each issuer has at most one chosen primary series.

### `core.price_daily`

| Column | Meaning |
|---|---|
| `issuer_cik`, `session` | Key |
| `price_source`, `ticker` | Where the row came from |
| `open`, `high`, `low`, `close`, `volume` | **As-traded** |
| `adj_close` | Split- and dividend-adjusted (for returns and volatility) |
| `cum_split_after` | Product of split ratios after this session. Split-adjusted price = as-traded ÷ `cum_split_after` |
| `split_ratio`, `dividend` | Events on the session |
| `dollar_volume` | `close × volume` |

- **Key**: (`issuer_cik`, `session`).
- **Validity**: `close > 0`, `low ≤ high`. `open` may be null or 0 when the provider has none; that is counted, not repaired.
- **Size**: about 18 M rows.

### `core.session`

(`session`, `session_no`): SPY's Yahoo sessions from `rules.price_history_start`, numbered 1, 2, …. It is the market calendar for "last session on or before T", "T+1" and session distances.

### `audit.price_issue`

(`price_source`, `ticker`, `session`, `issue`, `detail`), where `issue` is one of:
- `duplicate_session`
- `nonpositive_close`
- `high_below_low`
- `open_outside_range`
- `zero_open`

## Reference data (Step 7)

| Table | Columns | Notes |
|---|---|---|
| `core.ff_factor_daily` | `date`, `factor` (`mkt_rf`, `smb`, `hml`, `rmw`, `cma`, `rf`, `mom`, `st_rev`), `ret` | Decimal returns (the file's percent ÷ 100) |
| `core.ff_industry_daily` | `date`, `scheme` (12 / 49), `industry_no`, `industry`, `weighting` (`vw` / `ew`), `ret` | −99.99 → null |
| `core.sic_industry` | `scheme`, `industry_no`, `industry`, `sic_from`, `sic_to` | From `Siccodes49` / `Siccodes12` |
| `core.me_breakpoint` | `month`, `n_firms`, `percentile` (5 … 100), `value_musd` | NYSE market-cap breakpoints |
| `core.tick_pilot` | `ticker`, `pilot_group` (`G1` / `G2` / `G3`), `valid_from`, `valid_to`, `listing_exchange` | Test-group intervals from FINRA's change file. `valid_to` is exclusive |

## Company data (Step 9)

### `core.issuer`

(`issuer_cik`, `name`, `sic`, `sic_label`, `exchanges`, `tickers`, `raw_path`) from the issuer's submissions file. These are **current** values: they are used only by the D45 fallback and for venue and reporting, never as information at T.

### `core.company_filing`

| Column | Meaning |
|---|---|
| `issuer_cik`, `accession` | Key |
| `form`, `filing_date`, `report_date`, `items` | As in the submissions file |

- **Scope**: every filing listed for the issuer except forms 3, 4, 5, 144 and their amendments. This includes filings made *about* the issuer, such as 25-NSE, SC 14D9, SC TO-T and 425.
- **Use**: delisting evidence, re-mapping, and F15 later.

### `core.xbrl_fact`

| Column | Meaning |
|---|---|
| `issuer_cik`, `concept` | `concept` ∈ `shares_outstanding`, `equity`, `assets`, `liabilities`, `cash`, `net_income` |
| `unit` | `shares` or `USD` |
| `period_start`, `period_end` | `period_start` is null for instants |
| `value`, `filed`, `accession`, `form`, `fp` | The **first-filed** value for this period |
| `tag_used` | `main` / `fallback` and the tag name |

- **Key**: (`issuer_cik`, `concept`, `unit`, `period_start`, `period_end`).
- **First-filed**: the earliest `filed`, then the smallest accession. Later restatements are dropped.
- **Fallback**: the fallback tag is used only for a period where the main tag has no value.

## Final events (Step 7)

### `core.price_check` (G8)

| Column | Meaning |
|---|---|
| `accession`, `line_sk` | The `core.transaction` line |
| `issuer_cik`, `trade_date`, `price` | From the line |
| `ref_session`, `low`, `high` | Last session on or before the trade date, as-traded |
| `passes_g8` | `low × (1 − tol) ≤ price ≤ high × (1 + tol)` |
| `reason` | `ok` / `outside_range` / `no_session` |
| `price_source` | |

- **Rows**: one per line passing G1–G6a at an issuer with a chosen series. Lines at unpriced issuers have no row (G8 skipped).

### `core.priced_purchase`

Same columns as `core.clean_purchase`, plus `g8_status` (`checked` / `skipped_unpriced`). It is rebuilt from lines passing G1–G6a, and G8 where checked, with the G6 minimum applied again.

### `evt.event_candidate`

| Column | Meaning |
|---|---|
| `candidate_id` | `"{issuer}:{group}:{T}"` |
| `issuer_cik`, `group`, `signal_date` (T), `signal_accession` | |
| `t_session`, `t_session_no` | Last session on or before T |
| `outcome` | `event` / `unpriced` / `cooldown` / `g7_issuer_type` / `g7_no_sic` / `needs_header` / `floor_price` / `floor_liquidity` / `floor_activity` |
| `price_source` | |

**Order of checks**: cooldown → G7 → priced → floors (research R7).

### `evt.event`

| Column | Meaning |
|---|---|
| `event_id` | `"{issuer}:{group}:{T}"`, matching feature 002's id format |
| `issuer_cik`, `group`, `signal_date`, `signal_accession`, `accepted_at_et` | |
| `t_session`, `entry_session` | Entry = the first session after T (never the same day) |
| `n_entities`, `total_value_usd`, `max_seniority` | From the window, as of T |
| `g7_sic`, `g7_sic_source` | `header` / `current` |
| `priced` | FALSE for unpriced events |
| `close_t`, `addv20`, `active_sessions_20` | Floor inputs (null when unpriced) |
| `shares_outstanding`, `shares_filed`, `market_cap` | Latest shares first filed on or before T × `close_t` |
| `in_labelled_window` | T ≥ 2012-01-01 (FALSE for warm-up events) |
| `price_source` | |

- **Rows**: kept candidates only (`event` and `unpriced` outcomes).
- **Key**: `event_id`.

### `evt.event_member`

(`event_id`, `accession`, `entity_id_at_t`, `entity_role_at_t`, `value_usd`), as in `evt.prelim_event_member`.

### `audit.event_funnel`

(`year`, `group`, `outcome`, `n`): candidate outcomes per year and group.

### `audit.price_coverage` (SC-001)

| Column | Meaning |
|---|---|
| `year`, `group`, `delisting_status` | `delisting_status` ∈ `listed` / `delisted` / `unpriced_issuer` |
| `events` | A and B1 events from the floors-off pass, from 2012 |
| `covered` | Of those, events whose chosen series spans sessions T−19 to T+1 |
| `share` | `covered ÷ events` |

### `audit.g8_rate` (SC-002)

(`year`, `lines_checked`, `lines_passed`, `rate`), plus a total row.

## Delistings (Step 8)

### `core.delisting`

| Column | Meaning |
|---|---|
| `issuer_cik` | Key |
| `last_session`, `price_source`, `ticker` | Last row of the chosen series |
| `class` | `acquired` / `performance` / `unknown` / `remap` |
| `remap_status` | `found` (re-mapped) / `not_found` (treated as unknown) / null |
| `evidence_form`, `evidence_date`, `evidence_accession` | The deciding filing (null for unknown) |
| `venue` | `nyse` / `nasdaq` / `other` |
| `delisting_return` | Main run (research R11) |
| `bound_low`, `bound_high` | −1.0 and 0.0 |

**Classes** are decided in this order: remap → acquired → performance → unknown (research R11).

## Costs (Step 10)

### `evt.event_cost`

| Column | Meaning |
|---|---|
| `event_id` | Key (priced events only) |
| `spread_ar`, `spread_cs` | Abdi–Ranaldo and Corwin–Schultz estimates over the 20 sessions to T |
| `tick`, `tick_floor`, `spread` | `spread = max(spread_ar, tick ÷ close_t)` |
| `volatility` | 63-session standard deviation of log returns of `adj_close` |
| `addv20`, `impact` | `impact = k · σ · √(Q ÷ ADDV20)` |
| `cost` | `spread + 2 · impact` |
| `n_returns` | Returns in the volatility window. The cost is null and flagged when fewer than `rules.min_volatility_returns` (40) |
| `price_source` | |

## Build log

Every step appends to `core.build_log`, as in feature 002: step, run time, input fingerprint and rows written.
