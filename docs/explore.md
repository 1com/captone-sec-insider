# Exploring the data

All data lives in one DuckDB database, `data/warehouse.duckdb`. To browse and query it in a SQL notebook in the browser (the official [DuckDB UI](https://duckdb.org/docs/1.5/core_extensions/ui)), run:

```
uv run sentinel explore
```

Then open **http://localhost:4213**.

- **Read-only.** The warehouse is attached as `warehouse` and cannot be changed from the notebook. Write `warehouse.<schema>.<table>`, or run `use warehouse;` first.
- **Stop it before building.** Press Ctrl-C in the terminal. While the explorer is open, `sentinel` steps that write to the warehouse (`stage`, `entities`, `gates`, `detect-prelim`, `fetch-headers`, `prices`, `reference`, `company-facts`, `detect`, `delistings`, `costs`, `build`) fail with a lock error.
- **Notebooks are saved.** The UI keeps its notebooks in `data/explore.duckdb`, which is never part of the research data.
- **Local only.** Queries run on this machine; the UI downloads only its own web page from `ui.duckdb.org`. Sign-in to MotherDuck is optional and not needed.
- **Memory.** Queries are capped at 3 GB, like the build steps.

## What is where

| Schema | Table | Rows (24 Oct 2026) | One row per |
|---|---|---|---|
| `stg` | `submission`, `reportingowner`, `nonderiv_trans`, `nonderiv_holding`, `deriv_trans`, `deriv_holding`, `footnotes`, `owner_signature` | 37.9 M in total | Row of the SEC file, typed. Columns keep the SEC names, plus `quarter` and `src_row` |
| `stg` | `load_report`, `conversion_issue` | 664; 0 | (table, quarter) row check; value that failed to convert |
| `core` | `filing` | 4,496,561 | Form 3/4/5 filing: issuer, filing date, form type, reported ticker (`symbol_raw`) |
| `core` | `entity_member` | 477,714 | Change of an owner's entity (co-filers count as one buyer from their first joint filing) |
| `core` | `owner_role` | 534,560 | Period in which an owner has one role at an issuer (`ceo_cfo`, `officer`, `director`, `ten_pct`, `other`) |
| `core` | `transaction` | 7,353,719 | Non-derivative trade line, with a pass/fail flag per gate (G1–G6a) |
| `core` | `clean_purchase` | 161,059 | Genuine open-market purchase filing of at least $25,000, with the buyer's entity, role and holdings |
| `evt` | `prelim_event` | 39,498 | Event: A (cluster), B1 (solo CEO/CFO) or B2 (solo officer or director) |
| `evt` | `prelim_event_member` | 70,831 | Purchase inside an event's 14-day window |
| `audit` | `funnel` | 664 | (quarter, gate): rows in and out |
| `core` | `filing_header`, `header_failure` | 34,092; 3 | Signal filing's EDGAR header: SIC at the time, acceptance time (ET); headers that could not be fetched |
| `core` | `symbol_map`, `symbol_unmatched` | 28,521; 2,016 | Issuer × ticker × dates, with price source; issuers with no usable ticker |
| `stg` | `price_yahoo` | 12,432,111 | Yahoo row as downloaded (split-adjusted), per ticker and day |
| `core` | `price_series` | 4,482 | Candidate price series per issuer, source and ticker, and whether it was chosen |
| `core` | `price_daily` | 11,340,220 | Issuer × trading day of the chosen series: as-traded prices and volume, adjusted close, split factor |
| `core` | `session` | 4,228 | Trading day (SPY's calendar from 2010), numbered |
| `core` | `ff_factor_daily`, `ff_industry_daily`, `sic_industry`, `me_breakpoint`, `tick_pilot` | 148,044; 3,210,674; 647; 24,180; 1,249 | French library factors and industry returns, SIC-to-industry ranges, NYSE size breakpoints; FINRA tick-size pilot intervals |
| `core` | `issuer`, `company_filing`, `xbrl_fact` | 6,577; 3,686,104; 1,611,553 | Company profile (today's values); non-insider filing; financial fact as first filed |
| `core` | `price_check`, `priced_purchase` | 210,185; 155,529 | Purchase line checked by G8; clean purchase rebuilt after G8 |
| `evt` | `event_candidate` | 45,834 | Candidate (issuer, group, T) with its outcome: event, unpriced, cooldown, G7, floors |
| `evt` | `event`, `event_member` | 23,727; 40,363 | Final event, priced or unpriced (entry session, G7 SIC, floor values, market cap); its purchases |
| `evt` | `event_cost` | 14,639 | Priced event's spread, volatility, impact and round-trip cost |
| `audit` | `event_funnel`, `price_coverage`, `g8_rate`, `price_issue` | 370; 60; 18; 197 | Outcome counts; price coverage; G8 pass rate; price-data problems |

Column meanings: [specs/002-insider-warehouse/data-model.md](../specs/002-insider-warehouse/data-model.md). The rules behind each table: [docs/initialplan.md](initialplan.md) §6.

Column meanings for the tables from 24 Oct: [specs/004-market-data-events/data-model.md](../specs/004-market-data-events/data-model.md).

**Not in the warehouse yet**: prices of delisted companies (Tiingo, from 29 October), delisting classes, labels, features and model predictions.

## Known quirks

- **Typo values.** Some filings report impossible prices, for example $200 million per share, so a few preliminary events and clean purchases show values in the trillions. The price check G8 removes them from `core.priced_purchase` and the final events; in the earlier tables, filter them out (e.g. `where total_value_usd < 1e9`).
- **Funds and blank-check companies** are still among the preliminary events. The issuer-type rule G7 removes them from `evt.event` (outcome `g7_issuer_type` or `g7_no_sic` in `evt.event_candidate`).
- **Unpriced events.** Until the Tiingo month, events at delisted companies are in `evt.event` with `priced = false` and no floor values.
- **Quoted text.** About 11% of footnotes keep the SEC files' CSV quoting, e.g. `"…(""Common Units"")…"`.

## Example queries

Events per year and group:

```sql
select year(signal_date) as year, "group", count(*) as events
from warehouse.evt.prelim_event
group by all order by all;
```

The clusters with the most separate buyers since 2012:

```sql
select e.signal_date, f.issuer_name, f.symbol_raw, e.n_entities, e.total_value_usd
from warehouse.evt.prelim_event e
join warehouse.core.filing f on f.accession = e.signal_accession
where e."group" = 'A' and e.in_labelled_window
order by e.n_entities desc, e.total_value_usd desc
limit 20;
```

Every clean purchase at one company, with the buyer's name:

```sql
select c.filing_date, o.rptownername, c.entity_role, c.value_usd, c.shares_before, c.shares_after
from warehouse.core.clean_purchase c
join warehouse.core.filing f using (accession)
join warehouse.stg.reportingowner o
  on o.accession_number = c.accession and o.quarter = c.quarter
where f.symbol_raw = 'JPM'
order by c.filing_date desc;
```

Who bought in one event:

```sql
select m.accession, o.rptownername, m.entity_id_at_t, m.entity_role_at_t, m.value_usd
from warehouse.evt.prelim_event_member m
join warehouse.core.filing f on f.accession = m.accession
join warehouse.stg.reportingowner o
  on o.accession_number = m.accession and o.quarter = f.quarter
where m.event_id = '40545:A:2022-05-03';  -- issuer CIK : group : signal date (General Electric)
```

Why a trade line was excluded (the first `false` flag is the deciding gate), and its footnotes:

```sql
select line_sk, security_title, trans_code, shares, price, fn_ids,
       g1_form4, g2_purchase, g3_common, g4a_no_checkbox, g4b_no_plan_fn,
       g5_no_offering_fn, g6a_timely_valued
from warehouse.core.transaction
where accession = '0000006281-22-000184';

select footnote_id, footnote_txt
from warehouse.stg.footnotes
where accession_number = '0000006281-22-000184';
```

The gate funnel over all quarters:

```sql
select gate, unit, sum(rows_in) as rows_in, sum(rows_out) as rows_out
from warehouse.audit.funnel
group by step, gate, unit order by step;
```

One final event followed through the tables (PayPal's cluster of 23 November 2021, the running example of the data lecture):

```sql
select event_id, signal_date, accepted_at_et, entry_session, g7_sic, close_t, addv20, market_cap
from warehouse.evt.event where event_id = '1633917:A:2021-11-23';

select m.accession, m.entity_id_at_t, m.entity_role_at_t, m.value_usd, f.filing_date
from warehouse.evt.event_member m join warehouse.core.filing f using (accession)
where m.event_id = '1633917:A:2021-11-23';

select candidate_id, outcome, t_session
from warehouse.evt.event_candidate where issuer_cik = '1633917' order by signal_date;
```

Files outside the warehouse can be queried directly; paths are relative to the project folder:

```sql
select "group", count(*) from read_parquet('data/provisional/events_PROVISIONAL.parquet') group by 1;
select * from read_csv('specs/002-insider-warehouse/audits/gates_kept.csv');
select * from read_parquet('data/mvp/work/features.parquet') limit 10;
```
