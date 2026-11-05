# Feature Specification: Results-day move model

**Feature Branch**: `006-results-move-model`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "Step 5: build the results-day move model (feature 006, issue #77)."

## Context

When a company reports its quarterly (10-Q) or annual (10-K) results, its share price often jumps or
falls sharply in a single day. A retail investor holding or considering the stock before results day
wants to know how violent that move is likely to be—not which direction it will go (which cannot be
predicted reliably), and not a single bare percentage that pretends to be exact, but a risk band
(1 to 5), the typical range of past moves in that band, and the calibrated chances of a move larger
than 5%, 10% and 20% beyond the market (decisions D60, D61, D62; `config/risk_params.yaml` v5).

The training set (`data/exports/ml/results_move.parquet`) has one row per results announcement
(8-K item 2.02 belonging to a 10-Q or 10-K) from 2010 to 2022, with features measured as of the
close before the release (`as_of`) and the answer `move`: the absolute return from that close to the
close after the 8-K was filed (`close_after`), minus the S&P 500 ETF (SPY) return over the same
days. The pre-registered naive baseline is `prev4_mean`, the mean of the company's previous four
results-day moves (`n_prev` counts how many earlier moves the company had).

The EDA (`notebooks/004-eda-results-move.ipynb`) found that:
- 157,566 development releases (5,947 companies) are eligible with an answer.
- The naive baseline (`prev4_mean`) ranks releases well (rank correlation 0.30–0.39 across test
  years 2019–2022), but because individual moves are skewed, the mean of four moves has a mean
  absolute error (0.046–0.052) no better than predicting one constant median for every stock
  (0.042–0.052).
- Recent stock volatility (`idio_vol_252`, `range_vol_21`, `vol_252`, `vol_63`) ranks the move just
  as strongly as the company's own results-day history ($\rho \approx 0.33$).
- Financial features are mostly missing in 2010–2011 (before XBRL tagging became widespread in
  2011–2012).
- About 1.9% of releases have windows of 5 or more calendar days between the release and the 8-K
  filing.

Per `AGENTS.md` and `docs/plan.md`, the model is first built, run and tuned end to end in
`notebooks/006-results-move-model.ipynb` so the researcher can inspect every table, chart and
choice. Once the researcher approves the chosen model level, its code moves into
`src/sentinel/models/` with tests and a CLI command, and the notebook imports that code and
reproduces the exact same numbers.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build, compare and choose the model in the notebook (Priority: P1)

The researcher opens `notebooks/006-results-move-model.ipynb`, runs it from top to bottom with one
command under the machine's 5 GB memory cap, and reads every step of the D60 evaluation on the
purged walk-forward test years 2019, 2020, 2021 and 2022:
- **Level 0 (Naive baseline)**: `prev4_mean` (with the training median as fallback when a company
  has no prior release, plus the constant training median shown alongside as a floor);
- **Level 1 (Simple rule)**: an explainable combination of the company's prior moves (shrunk toward
  the sector median when `n_prev` is small) and its recent price volatility, fitted on each fold's
  training rows only;
- **Level 2 (Classic model)**: a regularised linear model on the log of the move with one feature
  kept per redundant pair, extreme ratios clipped at the training 1st and 99th percentiles, missing
  values filled with the training median plus a "was missing" indicator, and standardised;
- **Level 3 (LightGBM)**: gradient-boosted trees predicting the log move, tuned using time-ordered
  validation inside the training years only (never touching the test year), with fixed seeds.

The notebook compares all four levels across the four test years, selects the **simplest level
within one standard error of the best**, shows what the model relies on, and explains every choice
in plain English in the Findings section.

**Why this priority**: the researcher must see and approve the model and its evidence in the
notebook before any production model code is frozen.

**Independent Test**: run `notebooks/006-results-move-model.ipynb` end to end under the 5 GB memory
cap; it finishes without errors, logs the runs, and outputs the comparison table, charts and
written Findings.

**Acceptance Scenarios**:

1. **Given** the development export `data/exports/ml/results_move.parquet`, **When** the notebook is
   executed from start to finish, **Then** it uses only eligible rows with `as_of <= 2022-12-31`,
   purges training rows whose `close_after` falls on or after 1 January of each test year, and
   reports train, purged and test row counts for 2019, 2020, 2021 and 2022.
2. **Given** the four model levels (Level 0 baseline, Level 1 rule, Level 2 classic, Level 3
   LightGBM), **When** each level is evaluated on test years 2019–2022, **Then** the notebook
   reports per-year and mean ± standard error for rank correlation (Spearman), mean absolute error,
   median absolute error, and log-scale error, and applies the one-standard-error rule to select the
   winning level.
3. **Given** the EDA's questions (training from 2012 vs 2010; test performance with and without
   windows of 5+ days; ablation of insider and macro families over 5 seeds), **When** the notebook
   runs, **Then** each check is shown with its numbers and explained in plain words.

---

### User Story 2 - Turn predictions into calibrated chances and five risk bands (Priority: P1)

A retail investor does not want a raw regression number; they want to know the chance that the
results-day move will exceed 5%, 10% and 20%, and which of five risk bands (1 = calmest to 5 = most
volatile) the release falls into, together with what actually happened in past releases in that band
(median move, middle-half range, and hit rates for 5%+, 10%+ and 20%+ moves).

**Why this priority**: constitution Principle IV and decision D62 require forecasts to be presented
as calibrated chances and five bands with historical hit rates, never as a bare number.

**Independent Test**: inspect section 8 of the notebook (and the saved model output); for each test
year 2019–2022, the predicted probabilities for moves > 5%, > 10% and > 20% are compared against
observed frequencies (calibration table, Brier score and log loss), and the five risk bands show
monotonically increasing observed median moves and hit rates.

**Acceptance Scenarios**:

1. **Given** a fold's training predictions and residuals, **When** probabilities of `move > 0.05`,
   `move > 0.10` and `move > 0.20` are calibrated using only training data, **Then** on the test
   years 2019–2022 the predicted chances beat the constant base-rate Brier score and match observed
   rates closely across probability bins.
2. **Given** five risk bands (quintiles of predicted move set on the training data), **When** test
   releases are placed into bands 1–5, **Then** each band reports its release count, observed median
   move, 25th–75th percentile range, and observed hit rates for > 5%, > 10% and > 20% moves.

---

### User Story 3 - Freeze the approved model in `src/sentinel/models/` and verify holdout readiness (Priority: P2)

After the researcher reviews the executed notebook and approves the chosen model level, the model's
training, calibration, band assignment, MLflow logging and `predict(model, rows)` scoring move into
`src/sentinel/models/` with unit tests and a CLI command. The notebook is updated to import that
module and must produce the exact same numbers. A dry run scores `latest.parquet` and the 2023+ rows
of `feature_snapshot.parquet` (features only, no answers) to prove the frozen model is ready for
daily scoring (009) and the one-shot holdout test (010).

**Why this priority**: required so `sentinel update` can score companies daily without running a
notebook, and so the sealed holdout test on 16 November cannot fail on column mismatches or missing
values.

**Independent Test**: run unit tests and run the model command twice; predictions are bit-identical,
MLflow records the run with git commit and data version, the dry run on 2023+ feature rows produces
zero unexpected NaNs on eligible rows, and re-executing the notebook gives the exact same metrics.

**Acceptance Scenarios**:

1. **Given** the approved model in `src/sentinel/models/`, **When** trained and evaluated twice with
   the fixed seed (`SEED = 0`), **Then** every test-year prediction, probability and band is
   identical.
2. **Given** the saved model artefact in MLflow, **When** `predict(model, rows)` is called on
   `data/exports/ml/latest.parquet` and on the 2023+ rows of `feature_snapshot.parquet`, **Then**
   features are selected by name, all preprocessing uses training-fitted parameters only, and every
   eligible row receives a valid predicted move, band (1–5) and probabilities (`p_move_5`,
   `p_move_10`, `p_move_20`) in $[0, 1]$.

### Edge Cases

- **First results release of a company (`n_prev == 0`, `prev4_mean` missing)**: 1,355 eligible
  development rows have no prior release; when scoring `latest.parquet` or `feature_snapshot.parquet`
  directly, `prev4_mean` and `n_prev` may also be absent from the input columns unless looked up
  from prior training releases. The model's preprocessing must populate `prev4_mean` and `n_prev`
  from known training releases when absent and impute any remaining missing value with the training
  sector/overall median plus a missingness flag, so every eligible row gets a valid forecast.
- **Zero or tiny moves**: 5 eligible development releases have `move == 0.0`; log transformations
  must use a small floor (e.g. `log(max(move, 1e-4))` or `log(move + epsilon)`) fitted/fixed without
  look-ahead so logs are always finite.
- **Extreme feature ratios and 2010–2011 missing financials**: financial ratios have long tails and
  are largely missing in 2010–2011; clipping at the training 1st/99th percentiles and median
  imputation with missingness indicators must be fitted strictly on each fold's training set.
- **Sealed holdout protection**: no answer from 2023 or later may be read or computed; `data/exports/reference/`
  is never opened.
- **Memory cap**: all training, walk-forward evaluation and dry-run scoring must complete within the
  5 GB memory cap (`MemoryMax=5G MemorySwapMax=0`).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The model MUST be developed, evaluated and documented in
  `notebooks/006-results-move-model.ipynb` following the ten sections in its header instructions.
- **FR-002**: The model MUST read only development rows (`as_of <= 2022-12-31`) from
  `data/exports/ml/results_move.parquet` (via `sentinel.eda.load("results_move")`), filtered to
  `eligible == True` and `move` present, sorted deterministically by `cik`, `as_of`.
- **FR-003**: `prev4_mean` and `n_prev` are explicitly declared as allowed input features alongside
  the point-in-time feature snapshot columns; identifier, date, flag and outcome columns (`move`,
  `close_after`, `filing_date`, `report_date`, `cik`, `as_of`, and eligibility/coverage flags) MUST
  NOT be used as features.
- **FR-004**: Evaluation MUST use the four purged walk-forward folds for test years 2019, 2020, 2021
  and 2022 (`as_of < Y-01-01` and `close_after < Y-01-01` for training); random splits MUST NOT be
  used anywhere.
- **FR-005**: All four model levels of D60 MUST be implemented and compared on the exact same test
  rows in each test year:
  - Level 0: naive baseline (`prev4_mean`, with training median fallback when `n_prev == 0`, and
    the constant training median reported alongside);
  - Level 1: a simple explainable rule combining shrunk company history (`prev4_mean` shrunk toward
    sector median by `n_prev`) and recent volatility (`vol_63` / `range_vol_21`);
  - Level 2: a regularised linear model (`Ridge`) on log-move with redundant features removed,
    1st/99th percentile clipping, median imputation + missing flags, and standardisation;
  - Level 3: a gradient-boosted tree model (`LightGBM`) on log-move tuned via time-ordered
    validation within the training years only, with fixed seed `SEED = 0`.
- **FR-006**: Primary selection across levels MUST follow the pre-registered one-standard-error rule
  of D60 (pick the simplest level whose mean test score across 2019–2022 is within one standard
  error of the best level), reporting Spearman rank correlation, mean absolute error, median
  absolute error, log-scale MAE, and calibrated probability Brier score / log loss.
- **FR-007**: The model MUST produce calibrated probabilities for `move > 0.05`, `move > 0.10` and
  `move > 0.20` (`p_move_5`, `p_move_10`, `p_move_20`) and assign each prediction to one of 5 risk
  bands (quintiles of predicted move fitted on training data) carrying historical hit rates, median
  move and interquartile range (25th–75th percentile).
- **FR-008**: The notebook MUST include the three diagnostic checks requested by D60 and the EDA:
  (a) training from 2012 vs 2010; (b) test metrics on all releases vs releases with windows under 5
  days; (c) feature-family ablation (refitting without insider features and without macro features
  across 5 seeds).
- **FR-009**: Every model run MUST be logged to MLflow (`data/mlflow.db`) with its git commit,
  export date, feature list, eligibility flag (`eligible`), seed, and per-year walk-forward metrics.
- **FR-010**: Once the researcher approves the notebook, the chosen model and its `predict(model, rows)`
  function MUST live in `src/sentinel/models/` (with unit tests and a CLI entrypoint), and the
  notebook MUST import it and produce identical numbers.
- **FR-011**: The saved model object MUST be self-contained (feature names, preprocessing parameters,
  calibrators, band cutoffs, training move history per CIK for fallback lookup, eligibility column
  name, seed, git commit, export date) and pass a dry run on `latest.parquet` and the 2023+ rows of
  `feature_snapshot.parquet`.

### Key Entities

- **Results-Move Release Row**: one company results announcement (`cik`, `as_of`), with 97 snapshot
  features, `sector`, and historical results-move summary (`prev4_mean`, `n_prev`), plus the target
  `move` and window end `close_after` in development data.
- **Fitted Results-Move Model Bundle**: a serialisable object containing the exact feature list,
  fitted preprocessor (clipper, imputer, missing indicators, scaler/encoder), estimator, probability
  calibrators for 5%/10%/20% thresholds, 5-band thresholds and summary table, known training release
  history per CIK, and provenance metadata.
- **Results-Move Forecast**: for any eligible row, the predicted move size, risk band (1–5), band
  historical median and interquartile range, and calibrated probabilities `p_move_5`, `p_move_10`,
  `p_move_20`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `notebooks/006-results-move-model.ipynb` executes start to finish in under 10 minutes
  under the 5 GB memory cap (`MemoryMax=5G MemorySwapMax=0`) and produces identical predictions on a
  second run.
- **SC-002**: The chosen model beats the Level 0 naive baseline (`prev4_mean`) on every test year
  2019–2022 in both Spearman rank correlation and mean absolute error, and beats the base-rate
  Brier score on the 5%, 10% and 20% move probabilities in every test year.
- **SC-003**: Across the 5 predicted risk bands on the pooled test years 2019–2022, observed median
  moves and observed hit rates for > 5%, > 10% and > 20% moves increase strictly from Band 1 to
  Band 5.
- **SC-004**: Dry-run scoring on `latest.parquet` and on the 2023+ rows of `feature_snapshot.parquet`
  completes with 0 unexpected missing predictions across all eligible rows and all probabilities in
  $[0, 1]$.
- **SC-005**: No committed notebook contains output cells, and written Findings quote aggregates
  only (never a single company's Tiingo-derived prices or returns).

## Assumptions

- The export in `data/exports/ml/` is the cleaned 30 October 2026 export (pipeline cleaning frozen
  at V2-32 per V2-33).
- In workflow step 1–3 (`AGENTS.md` Step 5), the model is built, executed and presented to the
  researcher in `notebooks/006-results-move-model.ipynb` first; step 4 (moving the approved model to
  `src/sentinel/models/` with CLI and unit tests) proceeds immediately after the researcher approves
  the executed notebook.
