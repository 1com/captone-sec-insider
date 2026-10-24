# Data Model: Stock Lookup

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md)

The app reads one file, `data/lookup.duckdb` (git-ignored, `Paths.lookup`), built by `sentinel lookup` from the warehouse tables in research R2 and nothing else. All tables are in schema `lookup`. CIKs are stored without zero padding; dates are SEC filing or trade dates. Market prices do not appear anywhere in the file.

## `lookup.meta`

One row.

| Column | Meaning |
|---|---|
| `data_as_of` | DATE: newest filing date in `core.filing` (2026-09-30 today) |
| `dataset` | VARCHAR: newest SEC data set, e.g. `2026q3` |
| `built_at` | TIMESTAMP (UTC) of the lookup build |
| `warehouse_built_at` | TIMESTAMP: newest `finished_at` in `core.build_log`, to detect a stale lookup |

## `lookup.issuer_search`

One row per company in `core.filing` (about 20,900).

| Column | Meaning |
|---|---|
| `issuer_cik` | Key |
| `name` | Current name: `core.issuer.name` when present, else the name on the newest filing |
| `names` | VARCHAR[]: every distinct name filed, for search |
| `tickers` | STRUCT(ticker, first_year, last_year)[]: normalised tickers from the filings and the current SEC tickers, newest first |
| `n_transactions`, `first_filing`, `last_filing` | For the result list ("1,234 transactions, 2006–2026") |

## `lookup.filing_owner`

One row per (filing, reporting owner).

| Column | Meaning |
|---|---|
| `accession`, `owner_cik` | Key |
| `issuer_cik`, `filing_date`, `document_type` | From `core.filing` |
| `owner_name` | `stg.reportingowner.rptownername` |
| `role`, `title`, `is_director`, `is_officer`, `is_ten_pct`, `is_other` | From `core.owner_role` as of `filing_date` (latest `valid_from ≤ filing_date`); null role → shown as "other" |

## `lookup.transaction`

One row per non-derivative transaction line, sorted by `issuer_cik`, then `filing_date desc, accession desc, line_sk`.

| Column | Meaning |
|---|---|
| `accession`, `line_sk` | Key |
| `issuer_cik`, `filing_date`, `document_type` | |
| `trans_date`, `trans_code`, `acq_disp` | As filed; the description comes from the glossary (research R6) |
| `security_title` | As filed |
| `shares`, `price`, `value_usd` | As reported (`value_usd` = shares × reported price, null if either is missing) |
| `shares_after`, `direct_indirect`, `nature_of_ownership` | The holding after the line |
| `fn_ids` | VARCHAR[]: footnotes the line cites |
| `owners` | STRUCT(cik, name, role, title)[]: the filing's owners and roles at the filing date, for display |

**Validation**: `(accession, line_sk)` unique; row count equals `core.transaction`; `trans_code` is in the glossary or null.

## `lookup.footnote`

One row per footnote cited by at least one transaction: `accession`, `footnote_id` (key), `text`.

## `lookup.holding`

One row per (filing, security title, holding): the shares held after the filing (research R5).

| Column | Meaning |
|---|---|
| `accession`, `security_title`, `direct_indirect`, `nature_of_ownership` | Key (`nature_of_ownership` empty string when null) |
| `issuer_cik`, `filing_date` | |
| `shares_after` | Shares held after the filing |
| `source` | `trade` (last line of the holding in `core.transaction`) or `holding` (`stg.nonderiv_holding`) |

A filing's owners come from `lookup.filing_owner`. An insider's history is the holdings of every filing they are an owner on, grouped by filing date and security title: direct, indirect and total.

## `lookup.event` and `lookup.event_member`

From `evt.prelim_event` and `evt.prelim_event_member`: SEC-only events, no price data.

| `lookup.event` | Meaning |
|---|---|
| `event_id` | Key, `"{issuer_cik}:{group}:{signal_date}"` |
| `issuer_cik`, `group` (`A`/`B1`/`B2`), `signal_date`, `signal_accession` | |
| `n_entities`, `total_value_usd`, `max_seniority` | As of T |

| `lookup.event_member` | Meaning |
|---|---|
| `event_id`, `accession` | Key |
| `filing_date`, `value_usd`, `entity_role_at_t` | |
| `owner_names` | VARCHAR[]: names on the member filing |

## What the app derives at request time

- **Code, form, role and event descriptions**: from `src/sentinel/api/glossary.py`, never stored.
- **EDGAR link**: `https://www.sec.gov/Archives/edgar/data/{issuer_cik}/{accession without dashes}/`.
- **Insider summary** on the company page: per owner, the number of filings, the first and last filing date, and the latest role, from `lookup.filing_owner`.

## Rebuild

`sentinel lookup` writes a shadow file and renames it over `data/lookup.duckdb` when complete, so a running server or a failed build never sees a half-built file. The build is deterministic: the same warehouse gives the same tables (sorted inserts; no float sums other than `value_usd`, copied as computed).
