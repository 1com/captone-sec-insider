# Data model: EDA and data-quality report

Nothing is written to the database. The notebooks read three files and produce findings.

## Training sets (read)

Defined by `sentinel export` (columns in the generated `data/exports/README.md`).

| Set | Key | Answer | Window end | Baseline | Extra columns |
|---|---|---|---|---|---|
| volatility | `cik`, `as_of` (month end) | `vol_63_future` (annualised, > 0) | `window_end` | `vol_63` | — |
| results_move | `cik`, `as_of` (release eve) | `move` (absolute, ≥ 0, market-adjusted) | `close_after` | `prev4_mean` (with `n_prev` moves behind it) | `filing_date`, `report_date` |
| dilution | `cik`, `as_of` (month end) | `dilution` (0 or 1) | `window_end` | base rate | — |

Common columns: identifiers and flags (`cik`, `as_of`, `month_end`, `release_eve`, `latest`,
`coverage`, `filer_type`, `foreign_filer`, `sector`, `active_filer`, `excluded`, `eligible`) and
about 100 features.

### Feature families (`sentinel.eda.FAMILIES`)

| Family | Columns (by name) |
|---|---|
| price | `ret_*`, `vol_*` (not `vol_63_future`), `range_vol_21`, `max_drawdown_252`, `near_high_252`, `beta_252`, `idio_vol_252`, `log_close`, `close`, `cum_split_after` |
| trading | `log_addv20`, `addv20`, `zero_volume_63`, `sessions_listed` |
| size | `market_cap`, `log_market_cap`, `shares_outstanding` |
| financials | `book_to_market` … `issue_proceeds_to_assets`, `months_since_report` |
| filing events | `n_*`, `days_since_results`, `days_to_next_results` |
| insider | `buy_*`, `sell_*`, `planned_sell_share_12m`, `ceo_cfo_sold_12m`, `offering_buy_value_12m`, `buyers_14d`, `net_buy_to_mcap_12m` |
| short volume | `short_ratio_*` |
| macro | `vix*`, `spy_vol_63`, `dgs*`, `t10y2y*`, `dff*`, `baa10y*`, `cpi_yoy`, `unemployment*` |

### Validation rules checked (become findings when broken)

- Keys unique; `as_of <= window_end` (or `close_after`); `as_of <= 2022-12-31`.
- Answers in range: `vol_63_future > 0`; `move >= 0`; `dilution` in {0, 1}.
- Ratios finite; counts ≥ 0; `close >= 0`; `market_cap > 0` where present.
- `eligible` implies `active_filer`, not `excluded`, `close >= 1`, `addv20 >= 10,000`,
  `sessions_listed >= 63`.

## Finding (produced)

| Field | Meaning |
|---|---|
| statement | one sentence in plain language |
| evidence | the count, share or measure, and the notebook section that shows it |
| kind | clean / cleaning rule / modelling advice / open question |
| rows affected | for a cleaning rule: how many rows and companies |
| action | for a cleaning rule: proposed decision number in `docs/decisions.md` |
