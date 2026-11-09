# Research: Volatility model (005)

Decisions taken while planning (9 Nov), each with why and what else was considered. Numbers come
from the export of 9 November 2026 and `notebooks/004-eda-volatility.ipynb`.

**The design check behind R3, R4 and R7** (`design_check.py`, in this folder). Choices about the
method are made on years *before* every test year: no row dated 2019 or later was read. For each
year V in 2014–2018, LightGBM learned from the rows whose answers were known before V (fixed
settings: 31 leaves, 200 rows per leaf, learning rate 0.05) and forecast the rows dated in V.
Mean absolute error of the log (V2-56; lower is better):

| Variant | 2016 | 2017 | 2018 | Mean |
|---|---|---|---|---|
| Naive baseline: `log(vol_63)` | 0.2847 | 0.2782 | 0.3038 | 0.2889 |
| Mean-reversion rule (slope 0.75–0.77) | 0.2644 | 0.2656 | 0.2887 | 0.2729 |
| LightGBM forecasting the log, squared-error loss | 0.2214 | 0.2667 | 0.2523 | 0.2468 |
| LightGBM forecasting the log, absolute-error loss | 0.2172 | 0.2693 | 0.2570 | 0.2478 |
| **LightGBM forecasting the change from `log(vol_63)`, squared-error loss** | 0.2281 | **0.2481** | **0.2487** | **0.2416** |
| LightGBM forecasting the change, absolute-error loss | 0.2205 | 0.2588 | 0.2563 | 0.2452 |

Share of answers inside an 80% range set on earlier years' out-of-sample errors (LightGBM,
the log, absolute-error loss, 400 trees):

| Range set on | 2016 | 2017 | 2018 | Mean |
|---|---|---|---|---|
| **all earlier years (from 2014), pooled (V2-10)** | **80.6%** | 66.3% | **77.9%** | **74.9%** |
| the year before | 78.2% | 68.3% | 69.9% | 72.1% |
| the training rows' own errors (Gemini's way) | 72.6% | 57.1% | 67.3% | 65.7% |

LightGBM fits of 1,000 trees took 6–14 seconds on 73,000–262,000 rows; the best number of trees
was 100 in 2017 and 400–1,000 in the other years.

## R1 · Rows and features

- **Rows**: `sentinel.eda.load("volatility")` (month ends, January 2012 – September 2022),
  `eligible_volatility` true and the answer present and above 0: 530,137 rows, 7,883 companies.
  The 93 answers of exactly 0 have no logarithm and are left out (EDA); 9,484 rows are price-only
  stocks (V2-26). Sorted by `cik`, `as_of`.
- **Features**: the 95 columns of `sentinel.eda.features()`; never the answer, `window_end`,
  `cik`, `as_of`, the flags, `sector` (the current SIC, not point-in-time, as in 006) or
  `cum_split_after` (look-ahead). Unlike 006, the release-timing features stay: these rows are
  month ends, ordinary days, and the daily scores score each company's newest row, also an
  ordinary day, so no input changes meaning between learning and scoring.

## R2 · Folds

- **Decision**: `eda.folds(rows, "volatility", 2014..2022)`, checked by `eda.check_folds`: for year
  Y the models learn from **inner** rows (answers known before 1 Jan Y−1); settings come from the
  **validation** year Y−1 (rows dated in Y−1 with answers known before Y); the **test** rows are
  dated in Y. **Only 2019–2022 are scored**; 2014–2018 are forecast in the same way only to give
  the 80% range its history of out-of-sample errors (R4), never to choose anything.
- **Rationale**: the answer is known three months after the row's date, so the purge removes about
  3% of rows before each test year (EDA); one validation year serves the settings without
  touching the test year, as in 006 and 007.

## R3 · The four levels

| Level | The forecast of log volatility | Fitted on |
|---|---|---|
| 0 Naive baseline | `log(vol_63)`: past volatility continues | — |
| 1 Rule | `a + b · log(vol_63)`, the EDA's mean-reversion line | `a`, `b` by least squares on inner rows |
| 2 Classic | `log(vol_63)` + a ridge regression of the change | inner rows; `alpha` in {1, 10, 100, 1000} on the validation year |
| 3 Trees | `log(vol_63)` + LightGBM's forecast of the change | inner rows; settings on the validation year |

- **The change, not the level** (levels 2 and 3): the models forecast `log(future) − log(past)`
  and add it to `log(vol_63)`. Best in the design check (0.2416 against 0.2468), and best in 2017,
  a calm year in which forecasting the level did no better than the rule: the change form keeps
  the stock's own past volatility as the starting point, which is what the EDA found to hold
  (volatility moves about a fifth of the way back toward normal each quarter). For the ridge it
  also means the penalty shrinks toward the naive baseline, not toward one volatility for all.
- **Squared-error loss for the trees**, although the deciding measure is the absolute error: the
  absolute loss was worse on average in the design check (0.2452 against 0.2416).
- **Classic preprocessing** (fitted on inner rows only, inside the model, V2-33): the volatility
  measures (`vol_21`, `vol_63`, `vol_252`, `range_vol_21`, `idio_vol_252`) as logs; one of each
  pair with |Spearman| ≥ 0.9 dropped (`eda.redundant_pairs` on the 2019 fold's inner rows, fixed
  for every fold, keeping the log versions and the key features); every column cut at its 1st and
  99th percentiles; missing values filled with the median plus a "was missing" indicator;
  standardised. All families stay in (the hypotheses judge them, V2-46).
- **Trees**: missing values left to the trees; learning rate 0.05, feature and row fraction 0.8,
  `deterministic=True`, 8 threads, `seed=0`. Grid on the validation year: `num_leaves` {15, 63}
  × `min_child_samples` {100, 500}, trees from {50, 100, 150, 200, 300, 400, 600, 800, 1000}
  (the design check's best ran from 100 to 1,000), read from one fit of 1,000 trees, never by
  early stopping (V2-49). Settings are chosen by the validation year's mean absolute log error.
- **Alternatives**: forecasting the level (rejected above); absolute-error loss (rejected above);
  a median (quantile) linear regression for level 2 (slow on 400,000 rows, and the ridge on the
  change already starts from the median-like baseline).

## R4 · The 80% range on all earlier years (V2-10)

- **Decision**: for each year Y, the range's two multipliers are the 10th and 90th percentiles of
  the out-of-sample errors (forecast minus answer, in logs) of every earlier year from 2014: each
  year t < Y as forecast by its own fold's model, which learned only from answers known before
  t−1 and chose its settings on t−1. Only errors whose answers were known before Y are used (the
  last months of Y−1 are not). The range is `exp(forecast − q90)` to `exp(forecast − q10)`; it is
  a `Dated` with Y's cutoff. The frozen model's range uses 2014–2022.
- **Rationale**: the design check found pooling all earlier years best on average (74.9% against
  72.1% for the year before and 65.7% for the training rows' own errors, which is the 65–67% the
  audit found in Gemini's model). It is what V2-10 decided: one year is one market mood.
- **Limit, said plainly**: a year unlike the years before it (2017 was unusually calm; 2020 had
  the crash) puts the errors off-centre and the range misses more often. The coverage is reported
  for every test year, not adjusted (adjusting after seeing the test years would flatter them).
- **Alternatives**: the year before only, the training rows' own errors (both rejected above); a
  range that widens with market volatility (a new method, not decided; possible later, 021).

## R5 · Measures and the choice

- **Deciding measure** (V2-56): the mean absolute error of the log, per test year. Beside it: the
  root mean squared error of the log, the rank correlation with the answer, the 80% range's
  coverage; the same for price-only stocks and US filers (FR-012).
- **Choice** (V2-50): order baseline, rule, ridge, LightGBM; each level's gap to the best per test
  year; of the levels whose mean gap is within one standard error of its four yearly gaps, the
  simplest. The textbook version is printed for reference.

## R6 · Bands

- **Decision**: five bands with edges at the quintiles of the out-of-sample forecasts of the same
  earlier years as the range (a `Dated` with the test year's cutoff). Per band and test year: rows,
  median forecast, median real volatility, the range's coverage.
- **Rationale**: pooled years give edges that mean the same from year to year (a band 5 stock is
  wild in any market), where one year's quintiles would move with that year's mood. D47: each band
  with its past outcome.

## R7 · Settings, determinism and run time

- Settings on the validation year only (R3); every model, range and set of band edges a `Dated`
  (V2-49); `SEED = 0`; rows sorted.
- Run time: about 10 folds × 4 settings of LightGBM (6–20 seconds each) plus the hypothesis checks
  (6 variants × 5 seeds × 4 folds with each fold's setting): expected 30–45 minutes.

## R8 · What the model uses, the leak check and the hypotheses

- **Importance**: LightGBM's gain and the ridge's standardised coefficients (2021 fold).
- **Leak check**: inputs are features only; no single feature's rank correlation with the answer
  above 0.95 in size.
- **Hypotheses** (V2-46): family checks on the chosen level (LightGBM if the baseline or the rule
  is chosen), five seeds (one for the ridge), every fold, the fold's settings: refit without the
  family; "adds" if the mean absolute log error worsens by more than one standard error of the four
  yearly changes. Families: H-V1 past volatility (`vol_21`, `vol_63`, `vol_252`, `range_vol_21`,
  `idio_vol_252`; for the change models `log(vol_63)` stays the starting point); H-V2 size and
  trading; H-V3 financials; H-V4 macro; H-V5 insider and short volume (expected to add nothing).
  Direction checks (rank correlation with the answer per test year, the expected sign in at least
  three of four): H-V1 `vol_63` (+) and the rule's slope below 1 in every fold; H-V2
  `log_market_cap` (−); H-V3 `loss_making` (+); H-V4 `spy_vol_63` (+). H-V6 is the level
  comparison: the chosen model beats the rule by more than one standard error of their yearly
  gaps.

## R9 · The frozen model and the dry run

- **Decision**: the chosen level made for target year 2023 exactly as for a test year (inner:
  answers known before 2022; settings from the rows of 2022; range and band edges from the
  out-of-sample history 2014–2022). One object (`VolatilityModel`, contracts/) with the forecast,
  the range, the band edges, the feature list, the eligibility flag `eligible_volatility`, seed,
  git commit, export date and data hash; `predict(model, rows)` gives the level, the range and the
  band. Fitted twice in the notebook: identical predictions (SC-002).
- **Dry run**: the eligible month-end rows of `feature_snapshot.parquet` dated 2023 or later and
  the eligible rows of `latest.parquet` of companies still trading; checks: one forecast per
  eligible row, low below level below high, bands 1–5.

## R10 · MLflow and the move to the package

- **MLflow**: `sqlite:///data/mlflow.db`, experiment `005-volatility` (trial runs in
  `005-volatility-trial`): one run per level and test year, the checks, the frozen model; tags:
  git commit, export date, data hash.
- **After approval** (FR-019): the code moves to `src/sentinel/models/volatility.py`, replacing
  Gemini's; `sentinel train volatility` builds the frozen model (it runs the walk-forward history
  from 2014 for the range: minutes, once); the paused daily scores use the model's bands instead of
  fixed cut-offs; unit tests as `test_models_results_move.py`.
