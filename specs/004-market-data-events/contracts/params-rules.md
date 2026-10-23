# Contract: Parameter File Additions (Feature 004)

Extends [../../002-insider-warehouse/contracts/params-rules.md](../../002-insider-warehouse/contracts/params-rules.md). `version` goes from 7 to 8. Every value below is locked by `prereg-v1` except `ops`.

```yaml
registered:
  delisting_returns:
    value:
      acquired: 0.0
      performance_nyse_or_nyse_american: -0.30
      performance_nasdaq: -0.55
      unknown_treated_as: performance
      other_venue_treated_as: performance_nasdaq      # new (spec Assumptions; research R11)
    register:
      value: "0% acquired; −30% NYSE/NYSE American; −55% Nasdaq and other venues; unknown = performance-related"

rules:
  # Final detection (plan §6.4; research R1, R7)
  final_detection_start: 2011-07-01      # six-month warm-up before labelled_window_start
  price_history_start: 2010-01-01
  # G7 (plan §6.2; D45)
  g7_excluded_sic: [6770, 6722, 6726]
  g7_no_sic: exclude                     # exclude | current_sic (§11 fallback, set by the D45 check)
  # Delistings (plan §6.7; research R11). Forms match by prefix, so amendments count.
  delisting_merger_forms: [DEFM14A, DEFM14C, PREM14A, PREM14C, SC 14D9, SC TO-T, SC 13E3, "425"]
  delisting_performance_forms: ["25", 25-NSE, 15-12B, 15-12G, 15-15D]
  delisting_notice_after_months: 12
  delisting_end_gap_sessions: 5
  remap_after_days: 90
  # Costs (plan §6.5, §6.8; research R13, R14)
  tick_size_usd: 0.01
  tick_size_pilot_usd: 0.05
  min_volatility_returns: 40

ops:
  reference_symbols: [SPY, IWM]
  yahoo_batch_size: 50
  yahoo_pause_seconds: 2
  tiingo_paid_from: 2026-10-29
  tiingo_paid_until: null                # set on subscribing
  tiingo_requests_per_second: 2
  tiingo_api_base: "https://api.tiingo.com/tiingo/daily"
  sec_companyfacts_url: "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
  sec_submissions_url: "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
  french_base_url: "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
  french_files: [F-F_Research_Data_5_Factors_2x3_daily_CSV.zip, F-F_Momentum_Factor_daily_CSV.zip,
                 F-F_ST_Reversal_Factor_daily_CSV.zip, 49_Industry_Portfolios_daily_CSV.zip,
                 12_Industry_Portfolios_daily_CSV.zip, Siccodes49.zip, Siccodes12.zip,
                 ME_Breakpoints_CSV.zip]
  finra_tick_pilot_url: "https://tsp.finra.org/finra_org/ticksizepilot/TSPilotChanges.txt"
  market_cap_examples: []                # 10 tickers, chosen in implementation (research R9)
```

The registered values already used unchanged are:
- `g8_tolerance`, `cooldown`, `price_floor`, `liquidity_floor`, `activity_floor`;
- `position_size`, `impact_coefficient`, `spread_addv_window`, `volatility_window`;
- `merger_lookback`, `delisting_returns`, `labelled_window_start`.

## Rules checked by tests

1. **Delisting register row.** `registered.delisting_returns` keeps its register block, and plan Appendix E's "Delisting returns" row is updated to the same value text, so `check_register` passes. Decision **D50** in plan §12 records the other-venue rule.
2. **G7 setting.** `rules.g7_no_sic` ∈ {`exclude`, `current_sic`}. `rules.g7_excluded_sic` is a list of integers.
3. **Dates.** `rules.final_detection_start < registered.labelled_window_start`, and `rules.price_history_start ≤ final_detection_start − 1 year`.
4. **Tiingo window.** If `ops.tiingo_paid_until` is set, it is after `ops.tiingo_paid_from`.
5. **Delisting forms.** The two form lists do not overlap.
