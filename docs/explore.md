# Exploring the data

All data lives in one DuckDB database, `data/warehouse.duckdb`. To browse and query it in a SQL notebook in the browser (the official [DuckDB UI](https://duckdb.org/docs/1.5/core_extensions/ui)), run:

```
uv run sentinel explore
```

Then open **http://localhost:4213**.

- **Read-only.** The warehouse is attached as `warehouse` and cannot be changed from the notebook. Write `warehouse.<schema>.<table>`, or run `use warehouse;` first.
- **Stop it before building.** Press Ctrl-C in the terminal. While the explorer is open, `sentinel` build steps (`stage`, `entities`, `gates`, `detect-prelim`) cannot write to the warehouse, and they fail with a lock error.
- **Notebooks are saved.** The UI keeps its notebooks in `data/explore.duckdb`, which is never part of the research data.
- **Local only.** Queries run on this machine; the UI downloads only its own web page from `ui.duckdb.org`. Sign-in to MotherDuck is optional and not needed.
- **Memory.** Queries are capped at 3 GB, like the build steps.

## What is where

| Schema | Table | Rows (23 Oct 2026) | One row per |
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

Column meanings: [specs/002-insider-warehouse/data-model.md](../specs/002-insider-warehouse/data-model.md). The rules behind each table: [docs/initialplan.md](initialplan.md) §6.

**Not in the warehouse yet**: prices, company financials (XBRL), industry codes from filing headers, labels, features and model predictions. They arrive in Steps 6–16 of the plan.

## Known quirks

- **Typo values.** Some filings report impossible prices, for example $200 million per share, so a few purchases and events show values in the trillions. The price check G8 (Step 7) removes them; until then, filter them out (e.g. `where total_value_usd < 1e9`).
- **Funds and blank-check companies** are still among the events. The issuer-type rule G7 removes them in Step 7.
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

Files outside the warehouse can be queried directly; paths are relative to the project folder:

```sql
select "group", count(*) from read_parquet('data/provisional/events_PROVISIONAL.parquet') group by 1;
select * from read_csv('specs/002-insider-warehouse/audits/gates_kept.csv');
select * from read_parquet('data/mvp/work/features.parquet') limit 10;
```
