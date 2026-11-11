# Data model: Price history repair (027)

Changes to the core layer (`docs/architecture.md`, layer 3b). Everything above it (features,
labels, serving, export) reads `core.price_daily` and `ref.security` as before.

## `core.price_choice`: one row per segment (changed)

| Column | Type | Meaning |
|---|---|---|
| cik | VARCHAR | the company |
| seq | INTEGER | 1 for the earliest segment, rising in time |
| source | VARCHAR | `yahoo` or `tiingo` (null when the company has no price: one row, `main`) |
| ticker | VARCHAR | the ticker of this segment's series |
| reason | VARCHAR | why this series (as today: `yahoo_primary`, `tiingo_resolved`, …; for an earlier segment `joined`) |
| trim_from | DATE | first day used |
| trim_to | DATE | last day used (null: open) |
| listed | BOOLEAN | the company is in today's SEC list |
| main | BOOLEAN | the segment that names the company's security (the latest) |
| adj_factor | DOUBLE | multiplier for this segment's adjusted prices (R10; 1 for the main segment) |

Rules: a company's segments do not overlap; (source, ticker, day) belongs to at most one company
across all segments (R5); `main` is unique per company.

## `core.price_decision`: every decision about a history (new)

| Column | Type | Meaning |
|---|---|---|
| cik | VARCHAR | the company |
| kind | VARCHAR | `joined`, `join_failed` (`gap`, `level`, `identity`), `cut_reuse`, `cut_hole`, `cut_blank_check`, `lost_to`, `kept_overlap` (a later user of the ticker: a sister company or a typo), `kept_remapped` (the series is not the earlier holder's prices), `kept_continuous` (an earlier holder without prices; the series trades on while the company filed under another ticker) |
| ticker | VARCHAR | the ticker concerned |
| source | VARCHAR | the provider of the series concerned |
| day_from | DATE | start of the stretch concerned |
| day_to | DATE | end of the stretch concerned |
| other_cik | VARCHAR | the other company (reuse, lost claim), if any |
| detail | VARCHAR | the reason in words (dates of the switch, the level ratio, the former name) |

## `core.blank_check_period` (new; built in the price step from the staged prices of the company's tickers)

| Column | Type | Meaning |
|---|---|---|
| cik | VARCHAR | the company |
| former_name | VARCHAR | the matching former name, or `SIC 6770` |
| valid_from | DATE | first day of the name |
| valid_to | DATE | last day of the name (the merger) |
| years | DOUBLE | length of the name period |
| near_10 | DOUBLE | share of priced days between $9 and $11 (null without prices) |
| counted | BOOLEAN | the period counts as blank-check days (R7: at most 3.5 years, or near $10 on half the days) |

## Raw files (new)

- `tiingo/former/<TICKER>.csv.gz`: Tiingo's daily prices of an old ticker from 1 Jan 2010.
- `tiingo/former_meta/<TICKER>.json.gz`: Tiingo's description of it (name, exchange, dates).

Each with a manifest line (`source` `tiingo`, keys `former/<T>` and `former_meta/<T>`, role
`original`); staged into `stg_tiingo.price` and `stg_tiingo.meta` like the other Tiingo files.

## `app.stock` (serving, changed)

Adds `listed_via` (the former blank-check name) and `listed_via_date` (its last day), both null for
companies that did not list through a SPAC merger.

## Audit output (new, private)

`data/audit/prices-<date>.json`, described in [contracts/audit.md](contracts/audit.md).
