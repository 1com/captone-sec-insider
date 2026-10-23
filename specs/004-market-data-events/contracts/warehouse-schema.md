# Contract: Warehouse Invariants (Feature 004)

Column lists are in [../data-model.md](../data-model.md). Extends [../../002-insider-warehouse/contracts/warehouse-schema.md](../../002-insider-warehouse/contracts/warehouse-schema.md). W1–W11 are unchanged, and W12 is replaced. `sentinel build` and `check_invariants` run all of them.

## Layout

- **Schemas**: no new schemas. Prices, reference, company and delisting tables go in `core`, events in `evt`, reports in `audit` (plan §8.1).
- **Sources**: every new table derives from `data/raw/` only. The market calendar is derived from SPY's stored prices.

## Invariants

| # | Invariant | Table(s) |
|---|---|---|
| W12 | Tiingo data exists only under `data/raw/tiingo/` and in the registered tables ([tiingo-register.md](tiingo-register.md)). Outside the paid window, none exists at all | files, registered tables |
| W13 | Keys unique: (`ticker`, `session`) in `stg.price_*`; (`issuer_cik`, `session`) in `core.price_daily`; (`issuer_cik`, `price_source`, `ticker`) in `core.price_series`; `event_id` in `evt.event` and `evt.event_cost`; `issuer_cik` in `core.delisting`; the `core.xbrl_fact` key | price, event, delisting and fact tables |
| W14 | Each issuer has at most one chosen primary series, and every `core.price_daily` row comes from a chosen series | `core.price_series`, `core.price_daily` |
| W15 | `close > 0` and `low ≤ high` in `core.price_daily`. For Yahoo rows, `close ÷ cum_split_after` equals the stored split-adjusted close to within 1e-6 relative | `core.price_daily`, `stg.price_yahoo` |
| W16 | Every `core.price_check` line is at an issuer with a chosen series. `audit.g8_rate` totals equal `core.price_check` counts | G8 |
| W17 | Every `core.priced_purchase.value_usd ≥ registered.g6_min_value` | `core.priced_purchase` |
| W18 | `entry_session > signal_date`, `t_session ≤ signal_date`, and `entry_session` is the next session after `t_session` | `evt.event` |
| W19 | No two events with the same issuer and group lie fewer than `registered.cooldown` sessions apart | `evt.event` |
| W20 | Every priced `event` outcome has `close_t ≥ price_floor`, `addv20 ≥ min_addv_usd` and `active_sessions_20 ≥ 18`. Every `event` and `unpriced` outcome has G7 passed | `evt.event`, `evt.event_candidate` |
| W21 | Every `evt.event` row has exactly one `evt.event_candidate` row, with outcome `event` or `unpriced`. Outcome counts equal `audit.event_funnel` | evt, audit |
| W22 | `shares_filed ≤ signal_date` for every event with a market cap, and each `core.xbrl_fact` row is the earliest filing for its key | `evt.event`, `core.xbrl_fact` |
| W23 | Every `core.delisting` issuer has a chosen series whose last session is before the data's last session minus `rules.delisting_end_gap_sessions`. `delisting_return` matches the class and venue rules | `core.delisting` |
| W24 | `evt.event_cost.cost ≥ evt.event_cost.spread ≥ tick ÷ close_t` where not null | `evt.event_cost` |
| W25 | **Truncation**: rebuilding with `cutoff = T` (filings, headers and facts filed ≤ T; price rows ≤ the last session on or before T) gives identical G8 results for lines traded ≤ T, and identical candidates, outcomes, floor values, events and market caps dated ≤ T | `sentinel detect` |

## Reports (data-quality targets, not hard invariants)

| Report | Target | Source |
|---|---|---|
| Price coverage of A and B1 events from 2012, before floors | ≥ 90%, by year and delisting status | `audit.price_coverage` |
| G8 pass rate | ≥ 95% | `audit.g8_rate` |
| Entry opens outside the day's range, or zero | counted and listed | `audit.price_issue` |
| XBRL coverage per item at event dates | reported | `coverage.md` |

A missed target is reported in `coverage.md` and the run notes. It is not fixed by moving the study window (constitution II).

## Determinism

The same `data/raw` content and `params.yaml` produce identical tables, compared as sorted sets. Sums of money use `exact_sum` (feature 002). Audit samples use fixed seeds.
