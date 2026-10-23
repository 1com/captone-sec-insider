# Contract: Hand-Audit Sheets (FR-016, FR-020, SC-003 – SC-005)

The sheets are written as UTF-8 CSVs to `specs/004-market-data-events/audits/`.
- **No accidental overwrites**: existing sheets are kept unless `--force` is given.
- **Committed**: the sheets hold public SEC data and identifiers only, never prices, so they are committed.
- **Researcher's columns**: the last columns are filled in by the researcher.

## `golden_set.csv`: 30 final events (`sentinel audit golden`)

- **Sample**: events in the labelled window, seed 20261025, 10 per group where possible. A group with fewer than 10 events gives its shortfall to A.
- **Rows**: one row per member purchase. Event-level columns repeat on each row.

| Column | Content |
|---|---|
| `seed`, `n` | 20261025; event number 1–30 |
| `event_id`, `group`, `issuer_cik`, `issuer_name`, `signal_date`, `entry_session` | The event |
| `accession`, `filing_date`, `entity_id_at_t`, `entity_role_at_t`, `owner_names`, `value_usd`, `trade_dates`, `prices` | One member purchase |
| `edgar_link` | Filing index of the accession |
| `insiders_ok`, `dates_ok`, `amounts_ok` | Blank. `yes`, `no` or `unclear`, filled once per event, on its first row |
| `notes` | Blank |

`sentinel audit golden-summary` reports events with all three checks `yes`. The target is 30 of 30, or every difference explained (SC-003).

## `delisting_audit.csv`: 30 issuers (`sentinel audit delistings`)

- **Sample**: seed 20261024, 10 each from `acquired`, `performance` and `unknown`. A shortfall is filled from the other classes.

| Column | Content |
|---|---|
| `seed`, `n` | |
| `issuer_cik`, `issuer_name`, `last_session`, `class`, `venue`, `delisting_return` | The classification |
| `evidence_form`, `evidence_date`, `evidence_link` | The deciding filing (blank for unknown) |
| `filings_link` | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=100` |
| `verdict` | Blank. `agree`, `disagree` or `unclear` |
| `true_class` | Blank. The researcher's class when they disagree |
| `notes` | Blank |

`sentinel audit delistings-summary` reports agreement per class and overall. The target is ≥ 90% (SC-004).

The sheet holds no prices: `last_session` is a date.

## `market_caps.csv` (`sentinel audit market-caps`, SC-005)

| Column | Content |
|---|---|
| `ticker`, `issuer_cik`, `session` | Latest session in the data |
| `shares_outstanding`, `shares_filed` | From `core.xbrl_fact` |
| `market_cap_pipeline` | Shares × as-traded close |
| `market_cap_yahoo`, `fetched_at` | Yahoo's reported value, stored raw under `data/raw/yahoo/market_cap/` |
| `ratio`, `within_5pct` | |

Prices are not written to the sheet. The two market caps are aggregates, kept to the nearest $1 million. The target is 10 of 10 within 5%, or each miss explained, for example by a share count filed months earlier (SC-005).
