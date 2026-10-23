# Contract: Warehouse Invariants

Column lists are in [../data-model.md](../data-model.md). This file lists what the tests check (FR-022 – FR-024).

## Layout

- **File and schemas**: one file, `data/warehouse.duckdb`. Schemas `stg`, `core`, `evt` and `audit`. Feature 003 adds `lab` and `feat`, and `hold` via its guarded job.
- **Raw only**: every table is derived only from `data/raw` (and, for `symbols`, the latest SEC ticker snapshot in `data/raw/sec/reference/`).
- **Rebuildable**: deleting the warehouse and running `sentinel build` recreates it. With headers already stored, no network is needed.

## Invariants (all tested)

| # | Invariant | Table(s) |
|---|---|---|
| W1 | Row count per (table, quarter) = source data rows | `stg.*` vs `stg.load_report` |
| W2 | (`quarter`, `src_row`) unique | every `stg` table |
| W3 | Primary keys unique: `accession`; (`accession`, `line_sk`); (`issuer_cik`, `owner_cik`, `valid_from`); `event_id` | `core.filing`, `core.transaction`, `core.entity_member`, `core.owner_role`, `core.clean_purchase`, `evt.prelim_event` |
| W4 | Every `core.transaction.accession` exists in `core.filing` | core |
| W5 | Funnel reconciles per quarter (in = out + removed; line gates chain) | `audit.funnel` |
| W6 | `core.clean_purchase.value_usd ≥ registered.g6_min_value` | core |
| W7 | Membership is monotonic: owners sharing an `entity_id` at T share one at every later date | `core.entity_member` |
| W8 | Every owner on an accession maps to the same entity at that accession's filing date | `core.entity_member`, `stg.reportingowner` |
| W9 | **Truncation**: rebuilding from records with `filing_date ≤ T` gives identical entities, roles, clean purchases and preliminary events for everything dated ≤ T | Steps 3–5 |
| W10 | Every preliminary event's issuer has a `core.symbol_map` row or a `core.symbol_unmatched` row | Step 6 |
| W11 | `core.symbol_map` holds no Tiingo-only ticker before the paid month (only tickers seen in SEC data) | Step 6 |
| W12 | No file under `data/` was written from Tiingo data | Step 6 (`find data -iname '*tiingo*'` is empty) |

## Determinism

The same `data/raw` content and `params.yaml` produce identical table contents. Rows are compared as sorted sets, and the audit samples use a fixed seed.
