# Data model: Results-day move model (006)

What the notebook works with, from the rows it reads to the object it freezes. Replaces Gemini's
data model of 30 Oct.

## Release row (input, `data/exports/ml/results_move.parquet`, read only)

One results announcement of one company, read through `sentinel.eda.load("results_move")`
(dated by 31 Dec 2022).

| Column | Role |
|---|---|
| `cik`, `as_of` | the company and the close before the release (the row's date); sort keys, never inputs |
| `filing_date`, `report_date` | the 8-K's filing and release dates; used only for the long-window check (R8) |
| `close_after` | the close after the filing: the day the move is known (`eda.WINDOW_END`); folds and `Dated` cutoffs |
| `move` | the answer: absolute return beyond SPY's from `as_of` to `close_after` |
| `prev4_mean`, `n_prev` | the company's mean of its previous four moves and how many earlier moves it had: inputs (declared, FR-002) |
| `eligible` | this question's flag: only rows where it is true are learned from and scored |
| the 95 features of `eda.features()` | inputs (minus the three release-timing features if R4 is accepted) |
| `sector`, `coverage`, `cum_split_after`, other flags | never inputs (R9: sector is not point-in-time; `cum_split_after` is look-ahead) |

Derived per row: `log_move = log(max(move, 0.0001))`; `above_5`, `above_10`, `above_20`
(move above 0.05, 0.10, 0.20); `long_window` (`filing_date − report_date` ≥ 5 days).

Validation: `eligible` true and `move` present; `close_after` after `as_of`; every
`close_after` on or before 31 Dec 2022 (`eda.check_folds` refuses otherwise).

## Fold (one per test year 2019–2022, and target year 2023 for the frozen model)

From `eda.folds(rows, "results_move")`: boolean masks `inner`, `gap`, `valid`, `purged`, `test`,
checked by `eda.check_folds` (disjoint, in time order, no holdout answer). Cutoffs:
`valid_start(Y) = 1 Jan Y−1` for the forecast models, `test_start(Y) = 1 Jan Y` for settings,
calibrations and band edges.

## Level (four, simplest first)

`baseline` (log `prev4_mean`), `rule`, `ridge`, `lightgbm` (research R5). Each gives, per release,
one forecast of the log move (`score`); per level and fold the notebook keeps the chosen setting,
the forecast model, its three calibrations and the test-year chances.

## Chances (three per release)

`p_move_5`, `p_move_10`, `p_move_20`: the calibrated chances of a move above 5%, 10% and 20%.
Always `0 ≤ p_move_20 ≤ p_move_10 ≤ p_move_5 ≤ 1` (SC-006). From the forecast also a typical size
`exp(score)` (for the absolute and log errors only; never shown as a forecast, D62).

## Band (five)

Edges at the quintiles of `p_move_10` on the validation year (V2-53). Per band and test year:
releases, mean forecast and real share above 5%, 10% and 20%, median move. Names as 007:
"1 · Very low risk" … "5 · Very high risk".

## Result row (one per level and test year; MLflow run)

`level`, `year`, `log_loss_5`, `log_loss_10`, `log_loss_20`, `log_loss_mean` (deciding),
`brier_5`, `brier_10`, `brier_20`, `rank_corr` (chance above 10% with the move), `mae`,
`mae_log`, the chosen setting, rows.

## Frozen model (`ResultsMoveModel`, one object)

See [contracts/model-contract.md](contracts/model-contract.md). State: fitted for target year 2023
→ saved (joblib, MLflow artifact) → loaded by 009 and 010. Never refitted after the holdout test
except by a logged refit (021).
