# Contract: `sentinel audit` and `sentinel fetch tiingo --former`

## `sentinel audit`

Reads `data/sentinel.duckdb` read-only (refuses while another process writes it). Prints, then
writes `data/audit/prices-<date>.json` (private) and `docs/report/data_audit.md` (counts and
pass/fail only; no price, date or company derived from Tiingo values). Exit code 0, or 1 when a
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

Run on the build of 11 November before any change, the counts equal the audit of that day:
1,162 companies with stored prices cut (943 by the listing start, 219 by another company's use; 256
with clear evidence), 370 ticker changes not joined, 39 listed and 28 disappeared companies with a
hole of over a year, 152 disappeared companies whose prices end over a year before their last
report, 83,024 ticker-days claimed twice on 120 tickers.

## `sentinel fetch tiingo --former`

Asks Tiingo, once, for each ticker named by a company's own evidence (Form 4 symbols, SEC lists)
with no stored series whose dates in Tiingo's list overlap the company's use; stores prices from
1 Jan 2010 and the description with manifest lines (`tiingo/former/`, `tiingo/former_meta/`).
Refuses outside the paid window (`tiingo.paid_from`–`paid_until`); skips a ticker already stored;
prints the number of tickers asked, stored, without data and failed. Repeating it asks nothing new.
