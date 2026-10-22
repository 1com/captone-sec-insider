# Contract: `config/params.yaml`

The single home of every numeric parameter (constitution Principle III). The file has three top-level sections. A key must never appear in more than one of them.

```yaml
version: 1                      # bump on any change; the run metadata records the file's SHA-256

registered:                     # one entry per Appendix E row — pre-registered
  g6_min_value:
    value: 10000
    unit: usd
    sensitivity: [5000, 25000]
    register:                   # verbatim cells of the Appendix E row
      parameter: "G6 minimum value"
      value: "$10,000 per entity per filing"
      sensitivity: "$5k; $25k"
  insider_data_period:
    value: {start: 2006q1, end: 2026q3}
    unit: quarter
    register:
      parameter: "Insider data period"
      value: "2006 Q1 – 2026 Q3"
      sensitivity: "—"
  # … every other Appendix E row (34 rows in v2.1)

ops:                            # operational settings — not research parameters, not registered
  sec_target_requests_per_second: 5
  sec_max_requests_per_second: 10
  http_timeout_seconds: 60
  http_max_attempts: 5
  http_backoff_base_seconds: 2
  http_backoff_max_seconds: 120
  sec_landing_page: "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
  sec_folder_patterns:
    - "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{key}_form345.zip"
    - "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{key}_form345.zip"
  sec_company_tickers_url: "https://www.sec.gov/files/company_tickers_exchange.json"
  tiingo_supported_tickers_url: "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
  required_archive_tables: [SUBMISSION, REPORTINGOWNER, NONDERIV_TRANS, FOOTNOTES]

provisional:                    # the pilot's simplified rules (Appendix A) — NOT pre-registered
  price_standin_floor: 2.0      # transaction price stands in for the market-price floor
  cooldown_calendar_days: 91
  min_buyers_cluster: 2
  common_title_regex: "..."
  excluded_title_regex: "..."
  plan_footnote_regex: "..."
  offering_footnote_regex: "..."
  ceo_cfo_title_regex: "..."
  tiingo_us_exchanges: [NYSE, NASDAQ, NYSE MKT, AMEX, NYSE ARCA]
  pilot_reference:              # figures the summary compares against (plan §5.2, A.1, A.3)
    by_start_year:              # plan §5.2: events (A+B1), companies, delisted in Tiingo, unmatched
      2006: {events: 21904, companies: 6682, delisted_in_tiingo: 1982, unmatched: 1233}
      2009: {events: 17636, companies: 5560, delisted_in_tiingo: 1657, unmatched: 708}
      2011: {events: 16085, companies: 5179, delisted_in_tiingo: 1515, unmatched: 572}
      2014: {events: 13404, companies: 4545, delisted_in_tiingo: 1234, unmatched: 413}
      2016: {events: 11162, companies: 4039, delisted_in_tiingo: 955, unmatched: 340}
    funnel_2019q1: {purchase_lines: 12796, original_form4: 11938, common: 12385, plan_fn: 5009, offering_fn: 107}
    funnel_2023q1: {purchase_lines: 6539, original_form4: 6015, common: 6240, plan_fn: 957, offering_fn: 118}
```

## Rules checked by tests

1. Every data row in the Appendix E table of `docs/initialplan.md` has exactly one `registered` entry whose `register.parameter` equals the row's *Parameter* cell.
2. That entry's `register.value` and `register.sensitivity` equal the row's *Value* and *Sensitivity* cells exactly, after trimming whitespace. Markdown emphasis is kept as written.
3. No `registered` entry exists without a matching Appendix E row.
4. `ops` and `provisional` entries carry no `register` block.
5. Targeted value assertions, for the parameters this feature uses:
   - `g6_min_value.value == 10000`;
   - `g6_timeliness.value == 30`;
   - `cluster_window.value == 14`;
   - `cluster_min_value.value == 100000`;
   - `labelled_window_start.value == 2012-01-01` (D42; 2016-01-01 when this feature was planned);
   - the `insider_data_period` range yields 83 quarters;
   - `ops.sec_max_requests_per_second <= 10`.
6. The regular expressions under `provisional` all compile.

## Change policy

Before the `prereg-v1` tag, edits are free, but the `version` must be bumped. After the tag, any change to `registered` must also be logged in the spec's decision log (constitution Principle III).
