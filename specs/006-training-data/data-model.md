# Data Model: Training Data

**Feature**: [spec.md](spec.md) | **Decisions**: [research.md](research.md)

Feature 002 and 004 conventions hold: lower-case columns, CIKs without zero padding, dates are market or filing dates. Every table with Tiingo-derived values has `price_source` and is in the Tiingo register.

## `lab.event_label` (Step 11)

One row per (event, horizon, measure), for priced A, B1 and B2 events with T ≥ 2012-01-01 and exit session ≤ 2022-12-31.

| Column | Meaning |
|---|---|
| `event_id`, `horizon`, `measure` | Key. `horizon` ∈ {5, 21, 63, 126, 252}; `measure` ∈ `spy`, `iwm`, `ind_ew`, `ind_vw`, `ff6` |
| `issuer_cik`, `group`, `signal_date` | From `evt.event` |
| `entry_session`, `exit_session` | T+1 and T+H |
| `end_session` | Last session with a stock price used (< `exit_session` when delisted) |
| `entry_at_close` | TRUE when the entry open was unusable (research R2) |
| `stock_return`, `bench_return` | Buy-and-hold returns over the window (`bench_return` null for `ff6`) |
| `gross` | BHAR = `stock_return` − `bench_return`, or the CAR for `ff6` |
| `delisted`, `delisting_class`, `delisting_return` | Research R5 |
| `gross_dl_zero`, `gross_dl_wipeout` | `gross` with the delisting return at 0% and −100% (equal to `gross` when not delisted) |
| `cost`, `net` | `evt.event_cost.cost`; `gross − cost` (null when the cost is null) |
| `price_source` | |

## `lab.purchase_outcome` (Step 11, for F10)

One row per priced clean purchase (`core.priced_purchase`, `g8_status` ≠ failed) whose 63-session window ends by 2022-12-31.

| Column | Meaning |
|---|---|
| `accession` | Key |
| `issuer_cik`, `entity_id`, `filing_date` | From the purchase |
| `entry_session`, `exit_session`, `window_end` | Session after the filing date; +63; its date |
| `gross` | 63-session BHAR against the equal-weighted industry |
| `cost`, `net` | Cost model at the filing date (formula of `evt.event_cost`); `gross − cost` |
| `price_source` | |

## `feat.event_features` (Step 12)

One row per priced event with T ≥ 2012-01-01.

| Column | Meaning |
|---|---|
| `event_id` | Key |
| `issuer_cik`, `group`, `signal_date`, `t_session` | |
| `f1` … `f23`, `f25` … `f29` | DOUBLE; definitions in plan §7.2 and research R8–R10 |
| `f24` | VARCHAR: Fama–French 12-industry short name |
| `f9_classified`, `f10_history` | Buyers classified for F9; earlier purchases counted for F10 |
| `price_source` | |

`f10` is null for events after 2022 (filled by the guarded job).

## `ml.dataset` (Step 14)

One row per group A event with a target (research R11).

| Column | Meaning |
|---|---|
| `event_id` | Key |
| `issuer_cik`, `signal_date`, `window_end` | `window_end` = date of the 63-session exit |
| `y`, `net_63`, `gross_63` | Target and the primary continuous labels |
| `x_f1` … `x_f29` | Model inputs: the features, with F2, F12, F16, F17 ÷ SPY close at T then log(1 + x); `x_f24` stays a sector name |
| `uniqueness` | Average uniqueness of the window (research R11) |
| `price_source` | |

## `ml.dataset_fold` (Step 14)

| Column | Meaning |
|---|---|
| `fold`, `event_id` | Key; `fold` = test year 2019 … 2022 |
| `part` | `fit`, `tune`, `calibrate`, `test` or `purged` |
| `weight` | Uniqueness normalised to mean 1 over the fold's training window (`fit`, `tune`, `calibrate`); 1 for `test` |

## `ml.dataset_summary` (Step 14)

Per fold and part: events, positives, sum of weights, effective sample size, and `dropped` (fold 1 below 500 fit events).

## `ml.dataset_version` (Step 14)

One row per build: `version` (hash of the dataset rows), `built_at`, `git_commit`, `params_sha256`, `rows`. The same rows are written to `data/ml/dataset-<version>.parquet` and `data/ml/dataset_fold-<version>.parquet`.
