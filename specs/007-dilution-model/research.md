# Research: Dilution model (007)

Decisions taken while planning, each with why and what else was considered. Numbers come from
the export of 30 October 2026 and `notebooks/004-eda-dilution.ipynb`.

## R1 · Features: the 96 export features minus `cum_split_after`

- **Decision**: use the 96 feature columns that `sentinel.eda.features()` returns, **except
  `cum_split_after`** (95 left). Never `dilution`, `window_end`, `cik`, `as_of`, the coverage
  columns or the flags (FR-002).
- **Rationale**: `cum_split_after` is the product of the company's split ratios *after* the row's
  day (`src/sentinel/core/prices.py`: "split-adjusted price = as-traded ÷ `cum_split_after`"). On a
  month-end in 2015 it already knows every split up to the export: look-ahead (constitution I). It
  is kept in the feature table only to convert counts and prices (`features/price.py`,
  "PRICE_EXTRAS"), but `eda.FAMILIES` files it under "price", so it would slip into the model.
  The EDA shows it relates to the answer (|AUC − 0.5| = 0.14, lift 3.1) through future reverse
  splits, and on today's rows it is almost always 1 (no future known): the model would learn a
  signal that does not exist when scoring. `log_close` (as-traded), the returns (ratios of adjusted
  prices) and market value (a ratio of split factors) are not affected.
- **Alternatives**: keep it (rejected: leak); report it to the researcher only (done as well: the
  closing message lists it, so 005 and 006 can check it too).

## R2 · Which rows

- **Decision**: `sentinel.eda.load("dilution")` (rows dated by 31 Dec 2022), keep
  `eligible_dilution` true and `dilution` present: 409,576 rows. Sorted by `cik`, `as_of`.
- **The 46 split-like "yes" answers stay in.** The spec assumed they would be left out by
  `sentinel.validation.split_dilution`, but that check reads `data/sentinel.duckdb`, which exists
  only on the researcher's machine. They are 0.12% of the 39,276 "yes" answers, so the effect on
  every measure is below rounding. The closing message asks the researcher for the list (or to
  add a flag to the export) so the frozen model can drop them before 010.
- **Alternatives**: approximate them from `cum_split_after` (rejected: that is the look-ahead
  column, and it cannot tell a real reverse-split-then-sale from a false one).

## R3 · Folds, purge and the inner validation year

- **Decision**: for each test year Y in 2019–2022: training rows have `window_end` before
  1 Jan Y (the purge drops rows dated before Y whose window reaches into it); test rows are dated
  in Y. Inside the training rows, the **last training year Y−1** is the inner validation and
  calibration slice: inner-train rows have `window_end` before 1 Jan Y−1, validation rows are dated
  in Y−1 (and, being training rows, end before 1 Jan Y). Counts must equal
  `sentinel.eda.purge_table`.
- **Rationale**: one time-ordered slice serves tuning (FR-009) and calibration (FR-010) without
  touching the test year; it mirrors the frozen model's set-up (R8).
- **Alternatives**: time-series cross-validation inside training (several slices: 3–4× the fits on
  a laptop for little gain); calibrating on the test year (forbidden).

## R4 · The four levels

| Level | What | Chance it gives |
|---|---|---|
| 0 Base rate | the training rows' dilution rate | one number for every row |
| 1 Rule | `n_offering_12m > 0` (the EDA's best rule, AUC 0.73) | the training rate among flagged rows, and among the rest |
| 2 Classic | L2-regularised logistic regression | calibrated chance |
| 3 Trees | LightGBM | calibrated chance |

- **Classic model preprocessing** (fitted on training rows only, inside the model, FR-008): drop
  the macro and short-volume families (EDA: |AUC − 0.5| ≤ 0.04); drop one of each pair with
  |Spearman| ≥ 0.9 found by `eda.redundant_pairs` on the **first fold's training rows** (fixed for
  all folds, so no test row shapes the list; keeps the log versions: `log_addv20`,
  `log_market_cap`, `log_close`); cut every feature at its 1st and 99th training percentiles; fill
  missing values with the training median and add a "was missing" indicator; standardise. The
  regularisation strength C is chosen from {0.01, 0.1, 1} on the validation year.
- **Trees** (LightGBM per D60; for now scikit-learn's histogram boosting, R10): on all 95 features, missing values left to the trees (they learn "missing"
  themselves), no cutting needed. Fixed: learning rate 0.05, feature fraction 0.8, bagging fraction
  0.8 every iteration, `deterministic=True`, fixed thread count, `seed=0`. Tuned on the validation
  year: `num_leaves` {15, 63} × `min_child_samples` {100, 500}, with early stopping (100 rounds) on
  validation log loss, at most 2,000 trees. Small grid on purpose: four folds on a laptop.
- **Alternatives**: more rules (the shelf and share-growth rules are weaker: AUC 0.69, 0.66; they
  are reported in the rule table for context only); random forest or sklearn boosting as level 3
  (D60 names LightGBM).

## R5 · Measures and the choice

- **Decision**: per test year: log loss (**primary**), AUC, Brier score (next to the base rate's
  0.0867) and top-tenth lift (`eda.auc`, `eda.top_decile_lift`). For each level: mean over the four
  years and its standard error (standard deviation / √4). **The simplest level whose mean log loss
  is at most the best level's mean plus that best level's standard error** is chosen (order:
  base rate, rule, classic, trees).
- **Rationale**: the product shows chances in bands with hit rates, so the forecast must be a good
  *chance*, which log loss judges (proper score); AUC alone ignores calibration. The 2022 test year
  has half the rows (January–June): reported with that note, weighted like the others (D60 reports
  every year).
- **Alternatives**: AUC as primary (listed for the researcher to confirm in the closing message).

## R6 · Calibration and bands

- **Decision**: levels 2 and 3 are fitted on the inner-train rows with the chosen settings, then
  calibrated with Platt scaling (a logistic fit of the answer on the model's log-odds) on the
  validation year; test-year chances are the calibrated ones. Raw and calibrated log loss are both
  shown. **Bands**: five groups with fixed edges at the quintiles of the calibrated chance on the
  validation year; each band's forecast mean and real dilution rate per test year.
- **Rationale**: Platt keeps the order of the scores (AUC unchanged), is stable with a 10% base
  rate and gives smooth chances; edges fixed before the test year make the band table honest.
- **Alternatives**: isotonic regression (steps, can overfit a single year); refitting on all
  training rows after calibration (the calibrator would no longer match the model).

## R7 · What the model uses and the family check

- **Decision**: trees: LightGBM gain importance (top 20); classic: standardised coefficients (top
  20 by size). Leak check: no input is a non-feature column; no single feature reaches AUC ≥ 0.95.
  **Family check (D60)**: refit LightGBM without the insider family, and without the macro family,
  each with seeds 0–4, on every fold; report mean log-loss change against the full model with its
  spread.
- **Alternatives**: SHAP values (slower, a new plot dependency; gain importance answers "does it
  make sense" here).

## R8 · The frozen model

- **Decision**: after the choice, refit the chosen level for the holdout year 2023 exactly as a
  fold: inner-train = rows with `window_end` before 1 Jan 2022, calibration and band edges from the
  2022 rows. Saved as **one object** (`DilutionModel`, see contracts/) with preprocessing,
  model, calibrator, band edges, feature list, eligibility flag `eligible_dilution`, seed, git
  commit, export date and data hash; one function `predict(model, rows)` returns the chance and the
  band. Dry run on `latest.parquet` and on `feature_snapshot.parquet` rows dated after 2022
  (features only; reading them computes no answer). Determinism: the final fit runs twice in the
  notebook and the two prediction arrays must be identical.
- **Alternatives**: an MLflow "pyfunc" model (more ceremony; can come with the move to
  `src/sentinel/models/`).

## R9 · MLflow and where things are written

- **Decision**: tracking at `sqlite:///data/mlflow.db` (`config.paths().mlflow_db`, as
  `docs/architecture.md` names it), artifacts in `data/mlartifacts/`; experiment
  `007-dilution`. One run per level and test year (params, four measures), one for the family
  check, one for the frozen model (object as artifact). Tags: git commit, export date (file date of
  `dilution.parquet`, 30 Oct 2026), data hash (first 12 hex of its SHA-256).
- **Conflict noted**: the notebook rules say "never write to `data/`", while the architecture puts
  the MLflow store there and the rules also demand MLflow logging. MLflow's store is the only
  thing written, and nothing in `data/exports/` is touched. Listed in the closing message.

## R10 · Running on the teammate's Mac

- **Decision (teammate, 1 Nov, with reservation)**: level 3 uses scikit-learn's
  `HistGradientBoostingClassifier` instead of LightGBM for now. LightGBM's macOS build needs the
  OpenMP runtime (`brew install libomp`), and the teammate prefers not to install it. Same method
  (histogram gradient boosting, modelled on LightGBM, native missing values), different settings
  names and defaults, so numbers are close but not identical. Mapping: `num_leaves` →
  `max_leaf_nodes`, `min_child_samples` → `min_samples_leaf`, `feature_fraction` →
  `max_features`; early stopping on the validation year via `fit(X_val=, y_val=)` (sklearn 1.9),
  so it stays time-ordered. No bagging fraction (not offered). **This deviates from D60** and is
  listed in the closing message for the researcher; switching back is one estimator in section 6.
  Threads limited to 4 (`threadpoolctl`) so the Mac stays usable; measured about 24 s per fit on
  the largest fold. Run with `uv run jupyter nbconvert --to notebook --execute --inplace
  notebooks/007-dilution-model.ipynb` (no `systemd-run` on macOS).
- **Alternatives**: install `libomp` and use LightGBM (cleanest; the teammate's choice for
  later); point LightGBM at scikit-learn's bundled `libomp` (fragile); XGBoost or CatBoost (new
  dependency, also off D60).
