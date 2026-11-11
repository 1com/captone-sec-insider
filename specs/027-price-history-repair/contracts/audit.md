# Contract: `sentinel audit` and `sentinel fetch tiingo-former`

## `sentinel audit`

Reads `data/sentinel.duckdb` read-only (refuses while another process writes it). Prints, then
writes `data/audit/prices-<date>.json` (private); with `--before <earlier JSON>` also
`docs/report/data_audit.md`, before and after side by side (counts and pass/fail only; no price,
date or company derived from Tiingo values). Exit code 0, or 1 when a
named case fails or a ticker-day is claimed twice.

### JSON layout

```json
{
  "build_date": "2026-11-13",
  "audit_date": "2026-11-13",
  "listed": {"companies": 7351, "priced": 7038},
  "families": {
    "cut_with_stored_prices": {"companies": 0, "company_months_2012_2022": 0,
                               "by_cause": {"listing_start": 0, "other_use": 0},
                               "clear_evidence": 0, "examples": []},
    "ticker_change_not_joined": {"companies": 0, "old_prices_stored": 0, "examples": []},
    "join_failed": {"companies": 0, "by_reason": {"gap": 0, "level": 0, "identity": 0}, "examples": []},
    "hole_over_a_year": {"listed": 0, "disappeared": 0, "examples": []},
    "hole_31_to_365_days": {"listed": 0, "examples": []},
    "listed_without_price": {"us": 0, "foreign": 0, "price_only": 0,
                             "other_ticker_has_data": 0, "examples": []},
    "disappeared_prices_end_early": {"companies": 0, "examples": []},
    "disappeared_us_with_form4_without_prices": {"companies": 0},
    "ticker_days_claimed_twice": {"rows": 0, "tickers": 0},
    "blank_check_periods": {"names": 0, "companies": 0, "counted": 0, "left_out": 0,
                            "rows_in_counted_periods": 0, "examples": []}
  },
  "named_cases": [{"case": "MGP Ingredients priced from 2010 across MGPI and CASK", "pass": true}],
  "coverage": [{"year": 2012, "status": "listed", "companies": 0, "priced": 0}]
}
```

Each example: `{"cik", "name", "ticker", "detail"}`; at most five per family, the same five on the
same build (ordered by CIK).

### The 11 November baseline

`sentinel audit` on the build of 11 November (before any change; `data/audit/prices-2026-11-11.json`):
1,162 listed companies cut although stored prices reach further back (944 at Tiingo's listing
start, 218 after another company's use; 269 with clear evidence the cut is wrong; 51,441
company-months of 2012–2022); 370 ticker changes not joined (old prices stored for 33); holes of
over a year in 39 listed and 28 disappeared companies (31–365 days: 72 listed); 313 listed
companies without a price (49 US, 5 foreign, 259 price-only; another ticker has data for 85); 152
disappeared companies whose prices end over a year before their last report; 3,084 disappeared US
companies with Form 4s and no prices; 83,024 ticker-days on 120 tickers given to two or more
companies; 686 SPAC-like former names (658 companies), 637 counted, 49 left out, 83,391 priced
days inside counted periods; 6 of 18 named cases pass. (The hand-run audit of the morning found
the same totals; it split the cuts 943/219 and counted 256 clear cases and 85 mid-length holes,
with slightly different definitions.)

## `sentinel fetch tiingo-former`

Asks Tiingo, once, for each ticker named by a company's own evidence (Form 4 symbols, SEC lists)
with no stored series whose dates in Tiingo's list overlap the company's use; stores prices from
1 Jan 2010 and the description with manifest lines (`tiingo/former/`, `tiingo/former_meta/`).
Refuses outside the paid window (`tiingo.paid_from`–`paid_until`); skips a ticker already stored;
prints the number of tickers asked, stored, without data and failed. Repeating it asks nothing new.
