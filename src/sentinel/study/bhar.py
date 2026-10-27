"""`src/sentinel/study/bhar.py`: BHAR summary tables and monthly cohort series for Step 13.

Pre-registered in initialplan.md §7.1:
- Development period: events with signal date T on or before 2022-12-31.
- Primary horizon: 63 trading sessions (~3 months).
- Primary benchmark: Fama-French 49 Equal-Weighted Industry (ind_ew).
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
import duckdb
import pandas as pd


@dataclass
class BHARSummaryRow:
    group: str
    horizon: int
    measure: str
    is_net: bool
    n_events: int
    mean: float
    median: float
    std: float
    pct_positive: float


def query_bhar_summary(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Extract comprehensive BHAR summary statistics across all groups, horizons, and measures."""
    sql = """
    with dev_events as (
        select event_id, "group"
        from evt.event
        where priced and signal_date <= '2022-12-31'
    ),
    labels as (
        select e."group", l.horizon, l.measure, l.gross, l.net
        from dev_events e
        join lab.event_label l using (event_id)
        where l.net is not null
    ),
    unpivoted as (
        select "group", horizon, measure, false as is_net, gross as ret from labels
        union all
        select "group", horizon, measure, true as is_net, net as ret from labels
    )
    select "group", horizon, measure, is_net,
           count(*) as n_events,
           avg(ret) as mean,
           median(ret) as median,
           stddev(ret) as std,
           avg(case when ret > 0 then 1.0 else 0.0 end) as pct_positive
    from unpivoted
    group by 1, 2, 3, 4
    order by "group", horizon, measure, is_net
    """
    return con.execute(sql).df()


def query_monthly_series(con: duckdb.DuckDBPyConnection, horizon: int = 63, measure: str = "ind_ew") -> pd.DataFrame:
    """Extract monthly cohort average net returns for Group A, Group B1, and Group B2.

    Returns a DataFrame with columns:
    [year_month, n_a, net_a, n_b1, net_b1, n_b2, net_b2, diff_a_b1, diff_a_b2]
    """
    sql = f"""
    with dev_events as (
        select event_id, "group", strftime(signal_date, '%Y-%m') as ym
        from evt.event
        where priced and signal_date <= '2022-12-31'
    ),
    monthly as (
        select e.ym, e."group",
               count(*) as n,
               avg(l.net) as avg_net
        from dev_events e
        join lab.event_label l using (event_id)
        where l.horizon = {horizon} and l.measure = '{measure}' and l.net is not null
        group by 1, 2
    ),
    months as (
        select distinct ym from dev_events order by ym
    )
    select m.ym,
           coalesce(a.n, 0) as n_a, coalesce(a.avg_net, 0.0) as net_a,
           coalesce(b1.n, 0) as n_b1, coalesce(b1.avg_net, 0.0) as net_b1,
           coalesce(b2.n, 0) as n_b2, coalesce(b2.avg_net, 0.0) as net_b2,
           (coalesce(a.avg_net, 0.0) - coalesce(b1.avg_net, 0.0)) as diff_a_b1,
           (coalesce(a.avg_net, 0.0) - coalesce(b2.avg_net, 0.0)) as diff_a_b2
    from months m
    left join monthly a on a.ym = m.ym and a."group" = 'A'
    left join monthly b1 on b1.ym = m.ym and b1."group" = 'B1'
    left join monthly b2 on b2.ym = m.ym and b2."group" = 'B2'
    order by m.ym
    """
    return con.execute(sql).df()


def query_breakdowns(con: duckdb.DuckDBPyConnection) -> Dict[str, pd.DataFrame]:
    """Calculate 63-day net BHAR breakdowns for Group A across size, cluster size, role, and year."""
    results = {}

    # 1. By Calendar Year
    sql_year = """
    select year(e.signal_date) as year,
           count(*) as events,
           avg(l.net) as mean_net,
           median(l.net) as median_net,
           avg(case when l.net > 0 then 1.0 else 0.0 end) as win_rate
    from evt.event e
    join lab.event_label l using (event_id)
    where e.priced and e."group" = 'A' and e.signal_date <= '2022-12-31'
      and l.horizon = 63 and l.measure = 'ind_ew' and l.net is not null
    group by 1 order by 1
    """
    results["by_year"] = con.execute(sql_year).df()

    # 2. By Cluster Size (Number of Buying Entities: 2, 3, 4+)
    sql_cluster_size = """
    select case when e.n_entities = 2 then '2 Buyers'
                when e.n_entities = 3 then '3 Buyers'
                else '4+ Buyers' end as cluster_size,
           count(*) as events,
           avg(l.net) as mean_net,
           median(l.net) as median_net,
           avg(case when l.net > 0 then 1.0 else 0.0 end) as win_rate
    from evt.event e
    join lab.event_label l using (event_id)
    where e.priced and e."group" = 'A' and e.signal_date <= '2022-12-31'
      and l.horizon = 63 and l.measure = 'ind_ew' and l.net is not null
    group by 1 order by 1
    """
    results["by_cluster_size"] = con.execute(sql_cluster_size).df()

    # 3. By CEO / CFO Participation
    sql_exec = """
    with exec_bought as (
        select distinct m.event_id
        from evt.event_member m
        where m.entity_role_at_t = 'ceo_cfo'
    )
    select case when x.event_id is not null then 'CEO/CFO Participated'
                else 'Directors / 10% Owners Only' end as role_category,
           count(*) as events,
           avg(l.net) as mean_net,
           median(l.net) as median_net,
           avg(case when l.net > 0 then 1.0 else 0.0 end) as win_rate
    from evt.event e
    join lab.event_label l using (event_id)
    left join exec_bought x using (event_id)
    where e.priced and e."group" = 'A' and e.signal_date <= '2022-12-31'
      and l.horizon = 63 and l.measure = 'ind_ew' and l.net is not null
    group by 1 order by 1
    """
    results["by_executive"] = con.execute(sql_exec).df()

    # 4. By Firm Size (Market Cap terciles / breakpoints)
    sql_size = """
    with sized as (
        select e.event_id, l.net,
               case when e.market_cap < 300000000 then 'Micro-cap (<$300M)'
                    when e.market_cap < 2000000000 then 'Small-cap ($300M-$2B)'
                    when e.market_cap is not null then 'Mid/Large-cap (>$2B)'
                    else 'Unclassified Size' end as size_bucket
        from evt.event e
        join lab.event_label l using (event_id)
        where e.priced and e."group" = 'A' and e.signal_date <= '2022-12-31'
          and l.horizon = 63 and l.measure = 'ind_ew' and l.net is not null
    )
    select size_bucket,
           count(*) as events,
           avg(net) as mean_net,
           median(net) as median_net,
           avg(case when net > 0 then 1.0 else 0.0 end) as win_rate
    from sized
    group by 1 order by 1
    """
    results["by_size"] = con.execute(sql_size).df()

    return results
