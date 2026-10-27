"""`src/sentinel/study/portfolio.py`: Calendar-time portfolio construction and factor regression for H3.

Pre-registered in initialplan.md §7.1 and §3.3:
- H3: The cluster effect survives standard risk factors.
  Tested via calendar-time equal-dollar portfolio of all active clusters in their 63-session window.
  Entry cost charged on entry, exit cost on exit. Days with < 10 positions excluded.
  Regressed on Fama-French 5 factors + Momentum (UMD) with Dimson lags (0, 1, 2).
  Newey-West standard errors with 10 lags.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
import duckdb
import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class FactorRegressionResult:
    n_sessions: int
    daily_alpha: float
    annualized_alpha: float
    se_alpha: float
    t_stat: float
    p_value_one_sided: float
    r_squared: float
    factor_betas: Dict[str, float]
    factor_t_stats: Dict[str, float]
    verdict: str


def build_calendar_time_portfolio(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Construct daily equal-dollar calendar-time portfolio of active Group A clusters."""
    sql = """
    with dev_events as (
        select e.event_id, e.issuer_cik, e.t_session,
               s.session_no as s_start_no,
               s.session_no + 63 as s_end_no,
               coalesce(c.spread / 2.0, 0.002) + 0.0005 as half_cost
        from evt.event e
        join core.session s on s.session = e.t_session
        left join evt.event_cost c using (event_id)
        where e.priced and e."group" = 'A' and e.signal_date <= '2022-12-31'
    ),
    event_sessions as (
        select d.event_id, d.issuer_cik, d.half_cost,
               cs.session, cs.session_no,
               cs.session_no = d.s_start_no as is_entry,
               cs.session_no = d.s_end_no as is_exit
        from dev_events d
        join core.session cs on cs.session_no between d.s_start_no and d.s_end_no
    ),
    event_rets as (
        select es.session, es.event_id,
               p.adj_close / lag(p.adj_close) over (partition by es.event_id order by es.session) - 1.0 as raw_ret,
               es.is_entry, es.is_exit, es.half_cost
        from event_sessions es
        join core.price_daily p on p.issuer_cik = es.issuer_cik and p.session = es.session
    ),
    event_net_rets as (
        select session, event_id,
               (coalesce(raw_ret, 0.0)
                - case when is_entry then half_cost else 0.0 end
                - case when is_exit then half_cost else 0.0 end) as net_ret
        from event_rets
        where raw_ret is not null
    ),
    daily_portfolio as (
        select session,
               count(*) as n_active,
               avg(net_ret) as port_ret
        from event_net_rets
        group by session
        having count(*) >= 10  -- exclude thin days (<10 positions) per plan
    ),
    factors_pivoted as (
        select date as session,
               max(case when factor = 'mkt_rf' then ret end) as mkt_rf,
               max(case when factor = 'smb' then ret end) as smb,
               max(case when factor = 'hml' then ret end) as hml,
               max(case when factor = 'rmw' then ret end) as rmw,
               max(case when factor = 'cma' then ret end) as cma,
               max(case when factor = 'mom' then ret end) as mom,
               max(case when factor = 'rf' then ret end) as rf
        from core.ff_factor_daily
        group by date
    )
    select dp.session, dp.n_active, dp.port_ret,
           dp.port_ret - f.rf as excess_ret,
           f.mkt_rf, f.smb, f.hml, f.rmw, f.cma, f.mom, f.rf
    from daily_portfolio dp
    join factors_pivoted f using (session)
    where dp.session between '2012-01-01' and '2022-12-31'
    order by dp.session
    """
    return con.execute(sql).df()


def test_h3_factor_regression(df: pd.DataFrame, nw_lags: int = 10) -> FactorRegressionResult:
    """Run calendar-time portfolio regression on FF5 + Momentum with Dimson lags 0, 1, 2."""
    factor_names = ["mkt_rf", "smb", "hml", "rmw", "cma", "mom"]
    df = df.copy()
    df["const"] = 1.0

    X_cols = ["const"]
    for f in factor_names:
        for lag in range(3):
            col_name = f"{f}_lag{lag}" if lag > 0 else f
            df[col_name] = df[f].shift(lag)
            X_cols.append(col_name)

    reg_df = df.dropna().copy()
    y = reg_df["excess_ret"].to_numpy()
    X = reg_df[X_cols].to_numpy()
    n, k = X.shape

    # OLS: beta = (X'X)^(-1) X'y
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    residuals = y - X @ beta

    # R-squared
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    ss_res = np.sum(residuals**2)
    r_squared = 1.0 - (ss_res / ss_tot)

    # Newey-West covariance matrix
    S = X * residuals[:, None]
    Omega = S.T @ S / n
    for lag in range(1, nw_lags + 1):
        weight = 1.0 - (lag / (nw_lags + 1.0))
        Gamma = S[lag:].T @ S[:-lag] / n
        Omega += weight * (Gamma + Gamma.T)

    V_nw = XtX_inv @ (n * Omega) @ XtX_inv
    se_nw = np.sqrt(np.maximum(np.diag(V_nw), 1e-12))
    t_stats = beta / se_nw

    alpha = beta[0]
    se_alpha = se_nw[0]
    t_alpha = t_stats[0]
    p_alpha_onesided = float(1.0 - stats.t.cdf(t_alpha, df=n - k))
    annualized_alpha = float((1.0 + alpha) ** 252 - 1.0)

    # Total Dimson beta per factor (sum of lags 0, 1, 2)
    factor_betas = {}
    factor_t_stats = {}
    for f in factor_names:
        indices = [X_cols.index(f)] + [X_cols.index(f"{f}_lag{l}") for l in (1, 2)]
        tot_b = float(sum(beta[idx] for idx in indices))
        factor_betas[f] = tot_b
        factor_t_stats[f] = float(t_stats[X_cols.index(f)])

    verdict = (
        "Reject Null (Statistically Significant Alpha > 0 Net of Factors & Friction)"
        if p_alpha_onesided < 0.05
        else "Fail to Reject Null (Alpha Not Statistically Significant)"
    )

    return FactorRegressionResult(
        n_sessions=n,
        daily_alpha=alpha,
        annualized_alpha=annualized_alpha,
        se_alpha=se_alpha,
        t_stat=t_alpha,
        p_value_one_sided=p_alpha_onesided,
        r_squared=r_squared,
        factor_betas=factor_betas,
        factor_t_stats=factor_t_stats,
        verdict=verdict,
    )
