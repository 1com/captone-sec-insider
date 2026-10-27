"""`src/sentinel/study/inference.py`: Econometric hypothesis testing for H1, H2a, and H2b.

Pre-registered in initialplan.md §7.1 and §3.3:
- H1: Clusters earn a positive mean 63-day industry-adjusted abnormal return, net of cost.
  Tested on the monthly series of average net BHARs with Newey-West standard errors (3 lags).
- H2a: Clusters outperform solo CEO/CFO purchases (Group A vs Group B1).
  Tested on the monthly difference series with Newey-West standard errors (3 lags).
- H2b: Clusters outperform solo director purchases (Group A vs Group B2, exploratory).
"""

from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class HypothesisResult:
    hypothesis: str
    description: str
    n_months: int
    mean: float
    se_nw: float
    t_stat: float
    p_value_one_sided: float
    bootstrap_ci_95: tuple[float, float]
    bootstrap_p_value: float
    verdict: str  # 'Reject Null (Statistically Significant)' or 'Fail to Reject Null'


def newey_west_mean_test(
    series: np.ndarray, lags: int = 3, one_sided: bool = True
) -> tuple[float, float, float, float]:
    """Compute mean, Newey-West standard error, t-stat, and p-value for series mean != 0."""
    x = np.asarray(series, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n == 0:
        return 0.0, 0.0, 0.0, 1.0

    mean_val = float(np.mean(x))
    residuals = x - mean_val

    # Gamma_0 (sample variance)
    gamma_0 = float(np.sum(residuals**2) / n)

    # Autocovariances Gamma_j with Bartlett kernel
    autocov_sum = 0.0
    for j in range(1, lags + 1):
        weight = 1.0 - (j / (lags + 1.0))
        gamma_j = float(np.sum(residuals[j:] * residuals[:-j]) / n)
        autocov_sum += 2.0 * weight * gamma_j

    v_nw = (gamma_0 + autocov_sum) / n
    se_nw = float(np.sqrt(max(v_nw, 1e-12)))

    t_stat = mean_val / se_nw
    df = n - 1

    if one_sided:
        p_val = 1.0 - stats.t.cdf(t_stat, df=df)
    else:
        p_val = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=df))

    return mean_val, se_nw, t_stat, float(p_val)


def moving_block_bootstrap(
    series: np.ndarray, block_length: int = 3, n_reps: int = 2000, seed: int = 42
) -> tuple[tuple[float, float], float]:
    """Moving-block bootstrap over months (Künsch 1989; Lyon, Barber & Tsai 1999)

    accounting for autocorrelation across adjacent holding periods.
    """
    x = np.asarray(series, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n <= block_length:
        return (float(np.min(x)), float(np.max(x))), 1.0

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_length))

    # All possible overlapping blocks
    blocks = [x[i : i + block_length] for i in range(n - block_length + 1)]
    n_available_blocks = len(blocks)

    boot_means = np.empty(n_reps, dtype=float)
    for r in range(n_reps):
        chosen_indices = rng.integers(0, n_available_blocks, size=n_blocks)
        sampled = np.concatenate([blocks[idx] for idx in chosen_indices])[:n]
        boot_means[r] = np.mean(sampled)

    ci_lower = float(np.percentile(boot_means, 2.5))
    ci_upper = float(np.percentile(boot_means, 97.5))
    boot_p_one_sided = float(np.mean(boot_means <= 0.0))

    return (ci_lower, ci_upper), boot_p_one_sided


def test_h1(monthly_df: pd.DataFrame, lags: int = 3) -> HypothesisResult:
    """Test H1: Clusters earn a positive mean 63-day net industry-adjusted BHAR."""
    # Filter to active trading months with events
    active = monthly_df[monthly_df["n_a"] > 0]
    series = active["net_a"].to_numpy()

    mean_val, se_nw, t_stat, p_val = newey_west_mean_test(series, lags=lags, one_sided=True)
    ci, boot_p = moving_block_bootstrap(series, block_length=lags)

    verdict = (
        "Reject Null (Statistically Significant Alpha > 0)"
        if p_val < 0.05
        else "Fail to Reject Null (Net Alpha Not Statistically > 0)"
    )

    return HypothesisResult(
        hypothesis="H1",
        description="Clusters earn a positive mean 63-day net industry-adjusted BHAR",
        n_months=len(series),
        mean=mean_val,
        se_nw=se_nw,
        t_stat=t_stat,
        p_value_one_sided=p_val,
        bootstrap_ci_95=ci,
        bootstrap_p_value=boot_p,
        verdict=verdict,
    )


def test_h2a(monthly_df: pd.DataFrame, lags: int = 3) -> HypothesisResult:
    """Test H2a: Clusters outperform solo CEO/CFO purchases (Group A vs Group B1)."""
    # Active months where both A and B1 had events
    active = monthly_df[(monthly_df["n_a"] > 0) & (monthly_df["n_b1"] > 0)]
    series = (active["net_a"] - active["net_b1"]).to_numpy()

    mean_val, se_nw, t_stat, p_val = newey_west_mean_test(series, lags=lags, one_sided=True)
    ci, boot_p = moving_block_bootstrap(series, block_length=lags)

    verdict = (
        "Reject Null (Clusters Significantly Outperform Solo CEO/CFO)"
        if p_val < 0.05
        else "Fail to Reject Null (No Significant Difference over Solo CEO/CFO)"
    )

    return HypothesisResult(
        hypothesis="H2a",
        description="Clusters outperform solo CEO/CFO purchases (A - B1)",
        n_months=len(series),
        mean=mean_val,
        se_nw=se_nw,
        t_stat=t_stat,
        p_value_one_sided=p_val,
        bootstrap_ci_95=ci,
        bootstrap_p_value=boot_p,
        verdict=verdict,
    )


def test_h2b(monthly_df: pd.DataFrame, lags: int = 3) -> HypothesisResult:
    """Test H2b: Clusters outperform solo director purchases (Group A vs Group B2, exploratory)."""
    active = monthly_df[(monthly_df["n_a"] > 0) & (monthly_df["n_b2"] > 0)]
    series = (active["net_a"] - active["net_b2"]).to_numpy()

    mean_val, se_nw, t_stat, p_val = newey_west_mean_test(series, lags=lags, one_sided=True)
    ci, boot_p = moving_block_bootstrap(series, block_length=lags)

    verdict = (
        "Reject Null (Clusters Significantly Outperform Solo Directors)"
        if p_val < 0.05
        else "Fail to Reject Null (No Significant Difference over Solo Directors)"
    )

    return HypothesisResult(
        hypothesis="H2b (Exploratory)",
        description="Clusters outperform solo director purchases (A - B2)",
        n_months=len(series),
        mean=mean_val,
        se_nw=se_nw,
        t_stat=t_stat,
        p_value_one_sided=p_val,
        bootstrap_ci_95=ci,
        bootstrap_p_value=boot_p,
        verdict=verdict,
    )
