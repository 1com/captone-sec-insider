# Research: Results-day move model (006)

Decisions taken while planning (9 Nov), each with why and what else was considered. Numbers come
from the export of 9 November 2026 and `notebooks/004-eda-results-move.ipynb`. This file replaces
Gemini's research of 30 Oct, which predates the audit of 4 Nov.

**The design check behind R3, R4 and R9.** Choices about the method are made on years *before*
every test year (spec: "chosen in the plan and on validation years, never on the test years").
For each of 2016, 2017 and 2018, LightGBM learned from the releases whose moves were known before
that year and scored the releases dated in it (about 12,600 a year); the three chances were
calibrated per event (Platt) cross-fitted by half-year inside the year, the same for every variant.
No row dated 2019 or later was read. Mean log loss of the three chances (lower is better):

| Variant | 2016 | 2017 | 2018 | Mean | vs reference |
|---|---|---|---|---|---|
| Base rates (one chance for every release) | 0.4398 | 0.4188 | 0.4496 | 0.4361 | +0.068 |
| `prev4_mean` turned into chances (the naive baseline) | 0.3981 | 0.3771 | 0.4034 | 0.3929 | +0.025 |
| **Reference**: one forecast of the log move, from 2010, all features | 0.3694 | 0.3560 | 0.3796 | 0.3683 | — |
| Training from 2012 instead of 2010 | 0.3712 | 0.3564 | 0.3797 | 0.3691 | +0.0008 |
| Without the three release-timing features (R4) | 0.3699 | 0.3581 | 0.3795 | 0.3691 | +0.0008 |
| With the sector as an input | 0.3696 | 0.3549 | 0.3776 | 0.3673 | −0.0010 |
| Three direct yes/no models instead of one forecast | 0.3686 | 0.3560 | 0.3789 | 0.3678 | −0.0005 |

Fixed settings (31 leaves, 200 releases per leaf, learning rate 0.05); the best number of trees
was 200, the smallest tried, in 14 of 15 fits. Every variant is within 0.001 of the reference,
against a lead of 0.025 over the baseline: none of these choices decides the model's quality;
they are decided on simplicity, honesty and the product. Script:
`specs/006-results-move-model/design_check.py`.

## R1 · Rows and features

- **Rows**: `sentinel.eda.load("results_move")` (releases dated by 31 Dec 2022), `eligible` true
  and `move` present: 156,926 releases, 5,937 companies. Sorted by `cik`, `as_of`. No row is
  dropped for doubt: the EDA found no doubtful answers in this set (the 69 company-years with five
  or six releases were found real by the validation round, V2-25).
- **Features**: the 95 columns of `sentinel.eda.features()` plus `prev4_mean` and `n_prev`
  (declared in the spec, FR-002), minus the three release-timing features if the researcher agrees
  (R4). Never `move`, `close_after`, `filing_date`, `report_date`, `cik`, `as_of`, the flags,
  `sector` (R9) or `cum_split_after` (look-ahead: the split ratios after the row's day, V2-38).
  `eda.features()` no longer returns `cum_split_after`; the model also excludes it by name.
- **`prev4_mean` is point-in-time**: the label code (`labels/risk.py`) averages the company's
  previous four moves, and each of them ended before the release's `as_of` (checked on 9 Nov:
  0 of 170,879 rows overlap). The EDA's suggested median of the previous four is not in the
  export, and the holdout test (010) and the daily scores receive only `prev4_mean`; the rule uses
  `prev4_mean` on the log scale instead (R5).

## R2 · Folds

- **Decision**: `eda.folds(rows, "results_move")`, checked by `eda.check_folds`, exactly as 007:
  for test year Y, models learn from **inner** releases (move known, `close_after`, before
  1 Jan Y−1); settings, calibration and band edges come from the **validation** year Y−1
  (releases dated in Y−1 with moves known before Y); **test** releases are dated in Y. Counts
  equal `eda.purge_table(rows, "close_after")`.
- **Rationale**: windows are 2–14 days long, so the purge and the gap remove only a few releases a
  year; one time-ordered validation year serves settings and calibration without touching the
  test year, and mirrors the frozen model (R11).

## R3 · How each level gives three chances

- **Decision**: every level forecasts **one number per release, the log of its move's typical
  size**; three calibrations turn it into the chances of a move above 5%, 10% and 20%. Each
  calibration is a Platt scaling (a logistic fit of "moved more than X" on the forecast) on the
  validation year, a `Dated` with the test year's cutoff; its slope must be positive (a bigger
  forecast never lowers a chance). Where two calibrations would cross (only at extreme
  forecasts), the chances are put in order: above 10% at most above 5%, above 20% at most above
  10% (SC-006); the notebook counts how often this happens.
- **Rationale**: a results-day move is roughly the stock's usual size of move times a random
  factor that is the same for every stock, so on the log scale one location forecast carries the
  three chances (the three events differ only in their cut-off); the design check found three
  direct yes/no models only 0.0005 better (two of three years), at three times the fits. One
  forecast also gives a typical size, which V2-41's "absolute and log errors reported beside it"
  need, keeps the three chances consistent, and makes the hypothesis checks a third as long.
- **Alternatives**: three direct yes/no models per level (rejected above); one ordered model with
  a common slope (equivalent here, less familiar); the empirical spread of past errors (assumes
  the forecast is unbiased, which shrunk forecasts are not; Platt corrects that).

## R4 · The three release-timing features (proposed, for the researcher)

- **Proposal**: leave out `days_since_results`, `days_to_next_results` and
  `months_since_report`.
- **Why**: on a release eve, the rows this model learns from, they describe the release's own
  timing (about 90 days since the last release, about 0 days to the expected one, about 3 months
  since the last report); on any other day they mean something else (a company that released
  results last week has 7 days since its last release, a value no release eve has). The holdout
  test (010) scores release eves like the training rows, but the daily scores and the app will
  score each company's latest row, any day of the quarter: there the model would extrapolate, or
  009 would have to invent eve values. Leaving them out means the model tested on the holdout is
  the model the app uses. Cost in the design check: +0.0008 (mixed: +0.0004, +0.0021, −0.0001); they carry 3% of the trees' gain.
- **Alternatives**: keep them and have 009 set each company's timing features to their expected
  eve values (an invented input, the same for nearly every company); keep them and score daily
  only on release eves (no forecast between releases).

## R5 · The four levels

| Level | The forecast of the log move | Fitted on |
|---|---|---|
| 0 Naive baseline | `log(prev4_mean)`; a company's first release gets the inner releases' typical (median) move | — |
| 1 Rule | `a + b·log(history) + c·log(vol_63)`, where history is `prev4_mean` shrunk toward the inner releases' typical move by `m / (m + k)`, `m = min(n_prev, 4)` | `a, b, c` by least squares on inner releases; `k` in {1, 2, 4} on the validation year |
| 2 Classic | ridge regression of the log move on the features | inner releases; `alpha` in {1, 10, 100, 1000} on the validation year |
| 3 Trees | LightGBM regression of the log move | inner releases; settings on the validation year |

- **Constant base rates** (the shares of releases known before the test year that moved more than
  5%, 10% and 20%) are shown beside every level as the floor every level must beat (SC-004); they
  are not a level, since the pre-registered naive baseline is `prev4_mean`.
- **Rule** (the EDA's advice, without the sector: R9): the company's own typical results-day move,
  trusted more the more releases it has, combined with how much the stock moves on ordinary days.
  Its two weights say how much each counts.
- **Classic preprocessing** (fitted on inner releases only, inside the model, V2-33): positive
  size-of-move measures enter as logs (`prev4_mean`, the volatilities: the log of the move rises
  with their logs); one of each pair with |Spearman| ≥ 0.9 dropped (`eda.redundant_pairs` on the
  first fold's inner releases, fixed for every fold, keeping the log versions); every column cut
  at its 1st and 99th percentiles; missing values filled with the median plus a "was missing"
  indicator; standardised. All families stay in (the hypotheses judge macro, insider and short
  volume, V2-46).
- **Trees**: missing values left to the trees; fixed learning rate 0.05, feature and row fraction
  0.8 (rows every iteration), `deterministic=True`, 8 threads, `seed=0`. Grid on the validation
  year: `num_leaves` {15, 63} × `min_child_samples` {100, 500}, and the number of trees from
  {50, 100, 150, 200, 300, 400, 600, 800} (the design check chose 200, its smallest), read from
  one fit of 800 trees, never by early stopping (V2-49).
- **Settings are chosen by the deciding measure**: for each candidate, the validation year's mean
  log loss of the three chances after their Platt calibration on that year (two numbers per
  event on about 13,000 releases: no candidate gains from it more than another).
- **Alternatives**: LightGBM's quantile or absolute loss (the log already tames the tail; Platt
  re-calibrates); the median of the previous four in the rule (not available to the holdout and
  daily rows, R1).

## R6 · Measures and the choice

- **Deciding measure** (V2-41): per test year, the mean of the three log losses. Beside it: each
  event's log loss and Brier score (with the base rates' Brier), the rank correlation of the
  chance above 10% with the move, and, from the forecast size (exp of the log forecast;
  `prev4_mean` itself for level 0), the mean absolute error and the mean absolute log error.
- **Choice** (V2-50): order baseline, rule, classic, trees; each level's gap to the best per test
  year; of the levels whose mean gap is within one standard error of its four yearly gaps, the
  simplest. The textbook version is printed for reference, as in 007.
- **Rationale**: as 007 (V2-37, V2-50); log loss judges ranking and honest chances together.

## R7 · Calibration and bands

- **Calibration**: R3. Calibration charts per event and test year (forecast against real share,
  in tenths of the forecast).
- **Bands** (V2-53): five groups by the calibrated chance above 10%, edges at its quintiles on the
  validation year (a `Dated` with the test year's cutoff). Per band and test year: releases, the
  forecast and real shares above 5%, 10% and 20%, and the median move. The table the app's hit
  rates come from (via 008).

## R8 · Checks asked by D60 and the EDA

- **Training from 2012 against 2010** (FR-012): the chosen level is refitted from 2012 on every
  fold and both are shown on the test years. The start is fixed at 2010 by the design check
  (2010 better by 0.0008) before any test year is read; the test-year check reports, it does not
  choose.
- **Long windows** (FR-012): the chosen level's measures on the test years with and without the
  releases whose 8-K came 5 or more days after the release (`filing_date − report_date`, 1.9%,
  EDA); reported only, the window rule is pre-registered.

## R9 · The sector is left out

- **Decision**: `sector` is not an input to any level, and the rule shrinks toward the typical
  move of all inner releases, not the sector's.
- **Rationale**: `ref.sector` is each company's sector from its **current** SIC code
  (`reference/build.py`), applied to every past row: not point-in-time (constitution I). A
  blank-check company that later merges with a drug developer is "health" in its rows from before
  the merger. The design check found it worth −0.0010 (two of three years); the price features
  already tell calm sectors (utilities, median move 1.8%) from wild ones (technology, 5.4%). The
  sector stays available for tables (results by sector) in the notebook.
- **Alternatives**: use it as the EDA suggested (rejected: look-ahead); a point-in-time SIC
  history (not in the data; a pipeline change).

## R10 · What the model uses, the leak check and the hypotheses

- **Importance**: trees' gain (top 20), the classic model's standardised coefficients (top 20).
- **Leak check**: no input is a non-feature column; no single feature reaches an AUC of 0.95 for
  any event.
- **Hypotheses** (V2-46, FR-013): family check on the chosen level (LightGBM if a rule level is
  chosen, as 007), five seeds (one for ridge, which has none), every fold, with each fold's
  settings: refit without the family, the deciding measure's change per test year, "adds" if the
  mean worsening exceeds one standard error of the four yearly changes. Families: H-R1 history
  (`prev4_mean`, `n_prev`); H-R2 volatility (`vol_21`, `vol_63`, `vol_252`, `range_vol_21`,
  `idio_vol_252`); H-R3 size and trading (both families); H-R4 financials (the family); H-R5
  macro (the family); H-R6 insider and short volume (both families; expected to add nothing).
  Direction checks (rank correlation with the move per test year, expected sign in at least three
  of four): H-R1 `prev4_mean` (+), H-R2 `idio_vol_252` (+), H-R3 `log_market_cap` (−), H-R4
  `loss_making` (+), H-R5 `vix` (+). H-R1 also needs the baseline's rank correlation above 0.

## R11 · The frozen model and the dry run

- **Decision**: the chosen level made for target year 2023 exactly as for a test year (inner:
  moves known before 2022; settings, calibration and band edges from the releases of 2022). One
  object (`ResultsMoveModel`, contracts/) with the forecast model, the three calibrations and the
  band edges, each a `Dated` with its cutoff, plus the feature list, eligibility flag `eligible`,
  seed, git commit, export date and data hash; `predict(model, rows)` gives the three chances and
  the band. Fitted twice in the notebook: identical predictions (SC-002).
- **Dry run**: the 54,767 eligible release-eve rows of `feature_snapshot.parquet` dated 2023 or
  later, and the eligible rows of `latest.parquet` (the code path the daily scores use), with
  `prev4_mean` and `n_prev` given explicitly as missing: their moves after 2022 are sealed until
  the holdout test, which computes them inside its guarded command. Checks: one prediction per
  eligible row, chances in [0, 1] and in order, bands 1–5.

## R12 · MLflow, run time and the move to the package

- **MLflow**: `sqlite:///data/mlflow.db`, artifacts in `data/mlartifacts/`, experiment
  `006-results-move`: one run per level and test year, one for the checks, one for the frozen
  model; tags: git commit, export date, data hash (as 007, R9 there).
- **Run time**: the design check fitted LightGBM in 4–7 seconds; the notebook's largest part is
  the hypothesis checks (six families, five seeds, four folds: about 140 fits). Expected under
  30 minutes.
- **After approval** (FR-019): the code moves to `src/sentinel/models/results_move.py`, replacing
  Gemini's (never evaluated as packaged, audit of 4 Nov); `sentinel train results_move` builds the
  frozen model; `scoring/daily.py` reads the new output (the chance above 10% as the forecast
  value, the three chances and the band name as extras), still paused (V2-42); the notebook
  imports the module and gives the same numbers; unit tests as `test_models_dilution.py`.
