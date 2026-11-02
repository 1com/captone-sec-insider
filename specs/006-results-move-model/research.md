# Research: Results-day move model (006)

## R1. Target transformation and back-transformation

**Decision**: Model the natural log of the move with a small floor,
$z = \log(\max(\text{move}, \varepsilon))$ with $\varepsilon = 10^{-4}$ (0.01%, one basis point),
and transform predictions back to the move scale using the empirical smearing / median adjustment on
the training residuals:
- For **point predictions targeting MAE** (mean absolute error is minimised by the conditional
  median): $\hat{m}_{\text{med}}(x) = \exp(\hat{z}(x) + \text{median}(r_{\text{train}}))$, where
  $r_{\text{train}} = z_{\text{train}} - \hat{z}_{\text{train}}$.
- We also check conditional mean smearing $\hat{m}_{\text{mean}}(x) = \exp(\hat{z}(x)) \cdot \overline{\exp(r_{\text{train}})}$
  on inner validation and use the median-adjusted back-transform because `move` is right-skewed and
  MAE is minimised by the conditional median.

**Rationale**: The EDA (`notebooks/004-eda-results-move.ipynb` §6) showed `move` is heavily
right-skewed (median 3.7%, mean 5.8%, 99th percentile 31%, max > 100%, and 5 rows with `move == 0`).
Fitting models directly on raw `move` with squared error lets a few 80%+ moves dominate the fit and
inflates predictions for ordinary releases (the exact reason `prev4_mean` has worse MAE than a
constant median). Modelling $z = \log(\max(\text{move}, 10^{-4}))$ stabilises variance across small
and large stocks and produces homoscedastic residuals on the log scale.

**Alternatives considered**: Raw-scale L1/quantile regression (slower for Ridge, doesn't directly
give a unified scale-location residual distribution for probability calibration). We also test
LightGBM with `objective="regression_l1"` vs `objective="regression"` on $z$ in inner validation.

## R2. Evaluation metrics and primary selection criterion (D60)

**Decision**: Report five complementary metrics on every test year (2019, 2020, 2021, 2022) and
their mean ± standard error across the four years ($n = 4$ folds, $\text{SE} = s / \sqrt{4}$):
1. **Spearman rank correlation ($\rho$)** between predicted move and actual `move` (higher is better).
2. **Mean Absolute Error (MAE)** on the move scale, $|\hat{m} - \text{move}|$ (lower is better).
3. **Median Absolute Error (MedAE)** on the move scale (lower is better).
4. **Log MAE** on the log-move scale, $|\log(\max(\hat{m}, 10^{-4})) - \log(\max(\text{move}, 10^{-4}))|$ (lower is better).
5. **Mean Brier score** (and log loss) averaged across the three calibrated event probabilities
   $\text{move} > 5\%$, $\text{move} > 10\%$ and $\text{move} > 20\%$ (lower is better).

For the **one-standard-error rule** across the four levels (Level 0 → Level 1 → Level 2 → Level 3),
we check both **Spearman rank correlation** and **Log MAE / Mean Brier score** (the EDA specifically
warned that raw MAE alone is a weak discriminator because a single constant gets 0.042–0.052). All
three criteria agree on which levels are within 1 SE of the best, and the comparison table displays
the 1-SE threshold for each metric explicitly.

**Rationale**: Matches the notebook header instructions ("Measures: rank correlation, mean and
median absolute error, and for the chances the Brier score and log loss") and the EDA's advice.

## R3. Design of the four levels

**Decision**:
- **Level 0 (Naive baseline)**: `prev4_mean` from `results_move.parquet`. For the ~0.9% of releases
  where a company has no prior release (`n_prev == 0`, so `prev4_mean` is NaN), fill with the fold's
  training median move so every test row can be scored fairly; also print the metric on the `n_prev >= 1`
  subset and the constant-median floor.
- **Level 1 (Explainable rule)**: Combine the two strongest signals found by the EDA—the company's
  historical results-day move (`prev4_mean`) and its recent stock volatility (`vol_63`)—with
  empirical-Bayes shrinkage for companies with few prior releases:
  1. Shrink `log(prev4_mean)` toward the training sector median log-move using weight
     $w = \frac{n_{\text{prev}}}{n_{\text{prev}} + k}$ (with $k = 2$, so a company with 4 prior
     releases gets $2/3$ weight on its own history, and a company with 0 gets the sector median),
     adjusted by the training median ratio between `move` and `prev4_mean` (since the mean of 4
     skewed moves is systematically higher than the median move).
  2. Convert `vol_63` (annualised daily volatility) to a 1-day move scale via the training median
     ratio of `move` to `vol_63 / sqrt(252)`.
  3. Combine the two on the log scale with weights fitted by 2-variable linear regression on the
     fold's training rows only.
- **Level 2 (Classic model — Ridge regression)**:
  - Prune redundant feature pairs ($|\rho| \ge 0.90$ on training data, keeping the more complete /
    interpretable member of each pair, e.g. `log_market_cap` over `market_cap`, `log_addv20` over
    `addv20`, `log_close` over `close`, `vol_63` and `idio_vol_252` over `vol_252`, etc.).
  - Include `log_prev4_mean` ($\log(\max(\text{prev4\_mean}, 10^{-4}))$), `n_prev`, and one-hot
    sector indicators.
  - Clip every continuous feature at its training 1st and 99th percentiles (V2-33).
  - Add a binary `_missing` indicator for every feature with training missing rate $\ge 1\%$ (plus
    `prev4_mean`), impute missing values with the training median, and standardise (`StandardScaler`)
    on the training fold.
  - Fit `Ridge` on $z = \log(\max(\text{move}, 10^{-4}))$, choosing `alpha` from
    `[10.0, 100.0, 1000.0, 5000.0]` via time-ordered inner validation (the last training year,
    purged).
- **Level 3 (LightGBM)**:
  - Uses the full allowed feature set (plus `prev4_mean`, `n_prev`, and `sector` encoded via
    training-fold statistics / categorical codes), with training 1st/99th percentile clipping on
    extreme ratios and explicit missing-value handling.
  - Tuned on time-ordered inner validation (the last two training years, purged) over a small,
    regularised grid (`num_leaves` $\in \{15, 31\}$, `min_child_samples` $\in \{100, 200\}$,
    `learning_rate` $= 0.05$, early stopping on inner validation, `random_state = 0`,
    `deterministic = True`, `force_col_wise = True`).

**Rationale**: Follows D60 and the notebook instructions verbatim while keeping every step fast,
transparent and 100% point-in-time.

## R4. Calibrating the chances (> 5%, > 10%, > 20%) and building the 5 bands

**Decision**:
- From the model's log-move prediction $\hat{z}(x)$, compute out-of-sample-style inner-validation
  (or cross-fitted time-ordered training) residuals $r = z - \hat{z}$.
- For each threshold $\tau \in \{0.05, 0.10, 0.20\}$, fit an `IsotonicRegression(out_of_bounds="clip",
  y_min=0.001, y_max=0.999)` mapping $\hat{z}$ to $\mathbb{I}(\text{move} > \tau)$ on the fold's
  purged inner validation / training predictions, enforcing monotonicity across thresholds:
  $p_{20}(x) \le p_{10}(x) \le p_{5}(x)$.
- **Five risk bands**: Cut $\hat{m}(x)$ at the training quintiles (20th, 40th, 60th, 80th
  percentiles of training predictions) to assign Band 1 (lowest predicted move) through Band 5
  (highest predicted move). Record for each band the observed median move, 25th–75th percentile
  range (interquartile range), and observed hit rates for > 5%, > 10% and > 20% moves across the
  test years.

**Rationale**: Isotonic regression on the single monotone score $\hat{z}(x)$ guarantees that a stock
with a higher predicted move always has at least as high a chance of a > 5%, > 10% and > 20% move
and never produces impossible probabilities outside $[0, 1]$.

## R5. Holdout-readiness for `latest.parquet` and `feature_snapshot.parquet`

**Decision**:
`results_move.parquet` (and the 010 holdout `results_move` table) includes `prev4_mean` and `n_prev`
computed by `labels/risk.py`. However, `latest.parquet` and `feature_snapshot.parquet` (which the
dry run in step 4 of the notebook instructions scores) contain only the 110 columns of
`feature.snapshot` and do not carry `prev4_mean` or `n_prev`.
Therefore, the saved model bundle stores a lookup dictionary `history_by_cik: dict[str, tuple[float, int]]`
of each company's latest known `(prev4_mean, n_prev)` at the end of the training period (2022-12-31).
When `predict(model, rows)` is called:
- If `prev4_mean` and `n_prev` are present in `rows` (as in walk-forward test folds and the 010
  holdout evaluation), it uses them directly.
- If they are absent from `rows` (as in `latest.parquet` or `feature_snapshot.parquet`), it fills
  them by looking up `cik` in `model.history_by_cik` (or `(NaN, 0)` for CIKs with no prior training
  release, which the model's imputer then handles cleanly).

**Rationale**: Guarantees that `predict(model, rows)` works identically on `results_move.parquet`,
`latest.parquet`, and `feature_snapshot.parquet` with zero missing-column errors.
