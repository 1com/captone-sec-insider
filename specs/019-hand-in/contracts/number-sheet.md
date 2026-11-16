# Contract: the number sheet (`docs/presentation/numbers.md`)

Written by `uv run python -m sentinel.presentation`, in seconds, read-only on its inputs; identical
inputs give an identical file. Never edited by hand.

## Layout

- A header: how it was generated, from which files and which serving copy (its data date), and
  "Every number is an aggregate over many companies".
- One table per group, columns `id | number | as shown | source | meaning`.

## Ids and sources

| Group | Ids | Source |
|---|---|---|
| Dilution, one-time test | `dil.rows`, `dil.first`, `dil.last`; `dil.ll.<level>` and `dil.auc.<level>` over all years for `base_rate`, `rule`, `logistic`, `lightgbm`; `dil.lift10.lightgbm`; `dil.best_years` (the years in which the chosen level had the lowest log loss); `dil.rate` (the share of rows that diluted); `dil.band<k>.forecast`, `dil.band<k>.real` for k = 1-5 over all years | `model_card.json` → `dilution.holdout` |
| Dilution, test years | `dil.test_ll.<level>` (mean of 2019-2022) | `model_card.json` → `dilution.test_years` |
| Results-day move, one-time test | `mov.ll.<level>` (mean log loss of the three chances) for `base_rate`, `baseline`, `rule`, `ridge`, `lightgbm`; `mov.ridge_better_years` | `model_card.json` → `results_move.holdout` |
| Volatility, one-time test | `vol.mae.<level>` (mean absolute log error) for `baseline`, `rule`, `ridge`, `lightgbm`; `vol.cov80.lightgbm` | `model_card.json` → `volatility.holdout` |
| Catching up (V2-70) | `cu.announced` (share of answers of 1 already announced, 2012 to mid-2022); `cu.auc_all`, `cu.auc_none`; `cu.band5_all`, `cu.band5_none` (test years) | `docs/report/dilution_catching_up.md`, sections 1 and 2 (first tables) |
| Price repair (027) | `audit.months_before`, `audit.months_after`; `audit.twice_before`, `audit.twice_after`; `audit.named` | `docs/report/data_audit.md` |
| The app today | `app.date`, `app.companies` (companies still trading), `app.forecasts` (forecasts served) | `data/serving.duckdb` (read-only) |

## Rounding ("as shown")

Log loss and mean absolute log error to 3 decimals; AUC to 2; shares as percentages (one decimal
below 1%, else whole numbers); counts with thousands separators; dates as "31 Jan 2023".

## Refusals

The command stops with a message, writing nothing, when an input is missing or a level, year or
table it expects is absent. A failed refusal leaves the previous sheet untouched.
