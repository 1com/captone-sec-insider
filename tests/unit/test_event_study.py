"""Unit tests for sentinel.study: econometric inference, BHAR summaries, portfolio regressions."""

import numpy as np
import pytest

from sentinel.study import bhar, inference, portfolio


def test_newey_west_mean_constant():
    """A constant non-zero series has zero variance and infinite t-statistic."""
    series = np.array([0.05, 0.05, 0.05, 0.05, 0.05])
    mean_val, se, t_stat, p_val = inference.newey_west_mean_test(series, lags=1)
    assert np.isclose(mean_val, 0.05)
    assert se < 1e-5
    assert t_stat > 1000
    assert p_val < 1e-4


def test_newey_west_ar1_properties():
    """A series with positive autocorrelation should have higher Newey-West SE than standard SE."""
    rng = np.random.default_rng(12345)
    # Generate AR(1) series with phi = 0.6
    n = 200
    eps = rng.normal(0, 1, size=n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.6 * x[t - 1] + eps[t]

    # Shift mean to 0.2
    x = x + 0.2
    naive_se = np.std(x, ddof=1) / np.sqrt(n)
    mean_val, nw_se, t_stat, p_val = inference.newey_west_mean_test(x, lags=3, one_sided=True)

    assert np.isclose(mean_val, np.mean(x))
    # Due to positive serial correlation, NW SE must be larger than naive iid SE
    assert nw_se > naive_se
    assert t_stat == mean_val / nw_se
    assert 0.0 <= p_val <= 1.0


def test_moving_block_bootstrap_reproducibility():
    """Bootstrap returns valid 95% confidence intervals and matches seed."""
    x = np.linspace(-0.02, 0.05, 50)
    ci1, p1 = inference.moving_block_bootstrap(x, block_length=3, n_reps=500, seed=42)
    ci2, p2 = inference.moving_block_bootstrap(x, block_length=3, n_reps=500, seed=42)

    assert ci1 == ci2
    assert p1 == p2
    assert ci1[0] < ci1[1]
    # Sample mean is inside the 95% CI
    assert ci1[0] <= np.mean(x) <= ci1[1]


def test_factor_regression_ols_synthetic():
    """Verify OLS factor regression recovers true alpha and betas on synthetic data."""
    import pandas as pd

    n = 500
    rng = np.random.default_rng(999)
    # 6 factors
    factors = ["mkt_rf", "smb", "hml", "rmw", "cma", "mom"]
    data = {"session": pd.date_range("2015-01-01", periods=n, freq="B").strftime("%Y-%m-%d")}
    for f in factors:
        data[f] = rng.normal(0.0003, 0.01, size=n)

    # True parameters: daily alpha = 0.0005 (+12.6% annualized)
    true_alpha = 0.0005
    true_beta_mkt = 1.10
    true_beta_smb = 0.80

    excess = true_alpha + true_beta_mkt * data["mkt_rf"] + true_beta_smb * data["smb"] + rng.normal(0, 0.002, size=n)
    data["excess_ret"] = excess
    df = pd.DataFrame(data)

    res = portfolio.test_h3_factor_regression(df, nw_lags=2)

    # Recovered alpha should be close to 0.0005
    assert np.isclose(res.daily_alpha, true_alpha, atol=0.0004)
    # Betas
    assert np.isclose(res.factor_betas["mkt_rf"], true_beta_mkt, atol=0.15)
    assert np.isclose(res.factor_betas["smb"], true_beta_smb, atol=0.15)
    assert res.r_squared > 0.80
    assert res.n_sessions == n - 2  # lost 2 sessions to Dimson lag 2
