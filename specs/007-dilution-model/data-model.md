# Data model: Dilution model (007)

## Training row (input, `data/exports/ml/dilution.parquet`)

| Field | Meaning | Use |
|---|---|---|
| `cik`, `as_of` | company and month end | sort key; never a feature |
| 95 features | price, trading, size, financials, filing events, insider, short volume, macro, known at the close of `as_of` | inputs (`eda.features()` minus `cum_split_after`, research R1) |
| `cum_split_after` | product of split ratios after `as_of` | **never an input** (look-ahead) |
| `eligible_dilution` | the question's universe (V2-27) | row filter: true |
| `dilution` | 1 / 0 / missing: shares up 10%+ within 182 days | the answer; rows with it missing are dropped |
| `window_end` | `as_of` + 182 days | purge only; never a feature |
| other flags, `coverage`, `filer_type`, `foreign_filer`, `sector` | descriptive | never inputs (`sector` may be used for reporting) |

Validation: (`cik`, `as_of`) unique; after filtering 409,576 rows, base rate 9.59%; every
`as_of` ≤ 2022-12-31.

## Fold (one per test year Y ∈ {2019, 2020, 2021, 2022})

| Part | Rows |
|---|---|
| train | `window_end` < 1 Jan Y |
| purged | `as_of` < 1 Jan Y and `window_end` ≥ 1 Jan Y (dropped) |
| inner-train | `window_end` < 1 Jan Y−1 |
| validation / calibration | `as_of` in Y−1 (and in train) |
| test | `as_of` in Y |

Validation: train/purged/test counts equal `eda.purge_table(rows, "window_end")`.

## Level (per fold)

| Level | Fitted on | Output |
|---|---|---|
| 0 base rate | train | constant chance |
| 1 rule `n_offering_12m > 0` | train | two chances (flagged / not) |
| 2 logistic | inner-train (C from validation), Platt on validation | calibrated chance |
| 3 LightGBM | inner-train (settings from validation), Platt on validation | calibrated chance |

Scores per (level, test year): log loss, AUC, Brier, top-tenth lift; summary per level: mean and
standard error over the four years. Choice: simplest level with mean log loss ≤ best mean + best
SE.

## Band

Five bands with edges at the quintiles of the calibrated chance on the validation (calibration)
year. Per (band, test year): rows, mean forecast chance, real dilution rate.

## Frozen model (`DilutionModel`)

The chosen level refitted for target year 2023 (inner-train `window_end` < 2022-01-01, calibration
and band edges from 2022 rows). Fields in [contracts/frozen-model.md](contracts/frozen-model.md).

State: *candidate* (saved, logged) → *approved* by the researcher → moved to
`src/sentinel/models/` → *frozen* for the holdout test (010).
