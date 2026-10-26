"""`sentinel features` (Step 12): `feat.event_features`, F1–F29 as of T (plan §7.2; feature 006
research R8–R10).

Point in time (constitution I): filings are those filed on or before the signal date T, prices
those of sessions up to T's session, XBRL values those first filed on or before T, and F10 uses
only purchase windows that ended before T. F10 needs returns, so it exists only for development
events (T by 31 December 2022); the guarded holdout job fills it for later events.
"""

from dataclasses import dataclass, field

import duckdb

from sentinel.config import registered_value
from sentinel.labels.returns import development_end
from sentinel.warehouse import require_tables

INPUTS = ["evt.event", "evt.event_member", "evt.event_cost", "core.clean_purchase",
          "core.transaction", "core.owner_role", "stg.reportingowner", "core.company_filing",
          "core.xbrl_fact", "core.price_daily", "core.session", "core.sic_industry",
          "lab.event_label", "lab.purchase_outcome"]  # fmt: skip
FEATURES = [f"f{i}" for i in range(1, 30)]
COLUMNS = (
    'event_id VARCHAR, issuer_cik VARCHAR, "group" VARCHAR, signal_date DATE, t_session DATE, '
    + ", ".join(f"{f} VARCHAR" if f == "f24" else f"{f} DOUBLE" for f in FEATURES)
    + ", f9_classified INTEGER, f10_history INTEGER, price_source VARCHAR"
)


@dataclass
class FeatureReport:
    events: int = 0
    non_null: dict[str, int] = field(default_factory=dict)


def _events(con, params: dict) -> None:
    start = registered_value(params, "labelled_window_start")
    con.execute(
        """
        create or replace temp table _fe as
        select e.event_id, e.issuer_cik, e."group", e.signal_date as t, e.t_session,
               s.session_no as t_no, s.session_no - 21 as t21, s.session_no - 252 as t252,
               e.n_entities, e.total_value_usd, e.market_cap, e.addv20, e.g7_sic,
               e.price_source,
               c.volatility, c.spread
        from evt.event e
        join core.session s on s.session = e.t_session
        left join evt.event_cost c using (event_id)
        where e.priced and e.signal_date >= cast(? as DATE)
        """,
        [str(start)],
    )


def _insider(con, params: dict) -> None:
    """`_fi`: F3–F8, F11–F15 (research R9)."""
    window = registered_value(params, "cluster_window")
    sell = registered_value(params, "selling_lookback")
    repeat = registered_value(params, "repeat_buying_lookback")
    con.execute(
        """
        create or replace temp table _fm as
        select m.event_id, m.entity_id_at_t as entity, m.entity_role_at_t as role, m.accession,
               m.value_usd, p.filing_date, p.shares_before, p.shares_after, p.opens_position
        from evt.event_member m join _fe using (event_id)
        left join core.clean_purchase p on p.accession = m.accession
        """
    )
    con.execute(
        """
        create or replace temp table _fent as
        select event_id, entity, any_value(role) as role, sum(value_usd) as value,
               arg_min({'before': shares_before, 'opens': opens_position},
                       (filing_date, accession)) as first,
               arg_max({'after': shares_after}, (filing_date, accession)) as last
        from _fm group by 1, 2
        """
    )
    con.execute(
        f"""
        create or replace temp table _fi as
        with ent as (
            select event_id,
                   max(value) / nullif(sum(value), 0) as f3,
                   count(*) filter (where role = 'ceo_cfo') as f4,
                   count(*) filter (where role = 'director') as f5,
                   count(*) filter (where role = 'ten_pct') as f6,
                   avg(ln(last.after / first.before))
                       filter (where first.before > 0 and last.after > 0) as f7,
                   count(*) filter (where first.opens) as f8
            from _fent group by 1
        ),
        filing_lag as (
            select m.event_id, avg(date_diff('day', t.trans_date, t.filing_date)) as f11
            from (select distinct event_id, accession from _fm) m
            join core.transaction t on t.accession = m.accession and t.passes_lines
            group by 1
        ),
        sales as (
            select e.event_id, s.accession, s.filing_date, s.value_usd
            from _fe e join core.transaction s on s.issuer_cik = e.issuer_cik
             and s.trans_code = 'S' and s.document_type = '4'
             and s.filing_date > e.t - interval {sell} day and s.filing_date <= e.t
        ),
        sold as (select event_id, sum(coalesce(value_usd, 0)) as f12 from sales group by 1),
        sellers as (
            select distinct s.event_id, s.accession, s.filing_date, o.rptownercik as owner_cik
            from sales s join stg.reportingowner o on o.accession_number = s.accession
        ),
        ceo_sold as (
            select distinct x.event_id
            from sellers x join _fe e using (event_id)
            asof join core.owner_role r on r.issuer_cik = e.issuer_cik
             and r.owner_cik = x.owner_cik and x.filing_date >= r.valid_from
            where r.role = 'ceo_cfo'
        ),
        repeat_buys as (
            select e.event_id, count(p.accession) as f14
            from _fe e left join core.clean_purchase p on p.issuer_cik = e.issuer_cik
             and p.filing_date >= e.t - interval {repeat} day
             and p.filing_date < e.t - interval {window - 1} day
            group by 1
        ),
        reports as (
            select e.event_id, date_diff('day', max(f.filing_date), e.t) as f15
            from _fe e join core.company_filing f on f.issuer_cik = e.issuer_cik
             and f.filing_date <= e.t and (f.form like '10-Q%' or f.form like '10-K%')
            group by e.event_id, e.t
        )
        select e.event_id, ent.f3, ent.f4, ent.f5, ent.f6, ent.f7, ent.f8, fl.f11,
               coalesce(sold.f12, 0) as f12,
               cast(e.event_id in (select event_id from ceo_sold) as DOUBLE) as f13,
               r.f14, rp.f15
        from _fe e
        left join ent using (event_id) left join filing_lag fl using (event_id)
        left join sold using (event_id) left join repeat_buys r using (event_id)
        left join reports rp using (event_id)
        """
    )


def _routine(con, params: dict) -> None:
    """`_f9`: F9, the opportunistic share of classified buyers (research R9)."""
    years = registered_value(params, "routine_definition")["same_calendar_month_prior_years"]
    con.execute(
        f"""
        create or replace temp table _f9 as
        with owners as (
            select distinct m.event_id, m.entity, o.rptownercik as owner_cik
            from _fm m join stg.reportingowner o on o.accession_number = m.accession
        ),
        trades as (
            select distinct ow.event_id, ow.entity, ow.owner_cik,
                   year(t.trans_date) as y, month(t.trans_date) as mo
            from owners ow join _fe e using (event_id)
            join stg.reportingowner o on o.rptownercik = ow.owner_cik
            join core.transaction t on t.accession = o.accession_number
             and t.issuer_cik = e.issuer_cik and t.trans_code in ('P', 'S')
             and t.document_type = '4' and t.filing_date <= e.t
             and year(t.trans_date) between year(e.t) - {years} and year(e.t) - 1
        ),
        months as (
            select event_id, entity, owner_cik, mo, count(distinct y) as n_month
            from trades group by all
        ),
        per_owner as (
            select t.event_id, t.entity, t.owner_cik, count(distinct t.y) as n_years,
                   (select max(m.n_month) from months m where m.event_id = t.event_id
                     and m.entity = t.entity and m.owner_cik = t.owner_cik) as best_month
            from trades t group by 1, 2, 3
        ),
        status as (
            select event_id, entity,
                   bool_or(n_years = {years} and best_month < {years}) as opportunistic,
                   bool_or(n_years = {years}) as classified
            from per_owner group by 1, 2
        )
        select event_id, count(*) filter (where classified) as f9_classified,
               count(*) filter (where opportunistic)
                   / nullif(count(*) filter (where classified), 0) as f9
        from status group by 1
        """
    )


def _hit_rate(con, params: dict) -> None:
    """`_f10`: F10, the buyers' shrunk past hit rate at this issuer (research R8)."""
    shrink = registered_value(params, "f10_shrinkage")
    k, months = shrink["k"], shrink["base_rate_months"]
    primary = registered_value(params, "primary_horizon")
    end = development_end(params)
    con.execute(
        f"""
        create or replace temp table _f10 as
        with dev as (select * from _fe where t <= cast('{end}' as DATE)),
        base as (
            select d.event_id,
                   coalesce(avg(cast(l.net > 0 as DOUBLE)), 0.5) as p_bar
            from dev d left join lab.event_label l on l.measure = 'ind_ew'
             and l.horizon = {primary} and l.net is not null and l.exit_session < d.t
             and l.exit_session >= d.t - interval {months} month
            group by 1
        ),
        hist as (
            select f.event_id, f.entity,
                   count(o.net) as n, count(*) filter (where o.net > 0) as h
            from _fent f join dev d using (event_id)
            left join lab.purchase_outcome o on o.event_id = f.event_id
             and o.entity_id_at_t = f.entity and o.exit_session < d.t
            group by 1, 2
        )
        select h.event_id, avg((h.h + {k} * b.p_bar) / (h.n + {k})) as f10,
               cast(sum(h.n) as INTEGER) as f10_history
        from hist h join base b using (event_id) group by 1
        """
    )


def _market(con) -> None:
    """`_fk`: F19–F21, F24, F26–F29 (research R10)."""
    con.execute(
        """
        create or replace temp table _fpx as
        select p.issuer_cik, s.session_no, p.adj_close,
               p.close / p.cum_split_after as close_s, p.high / p.cum_split_after as high_s
        from core.price_daily p join core.session s using (session)
        where p.issuer_cik in (select issuer_cik from _fe) and p.adj_close > 0
        """
    )
    con.execute(
        """
        create or replace temp table _fk as
        with px_t as (
            select e.event_id, p.adj_close as a, p.close_s
            from _fe e asof join _fpx p on p.issuer_cik = e.issuer_cik and e.t_no >= p.session_no
        ),
        px_21 as (
            select e.event_id, p.adj_close as a
            from _fe e asof join _fpx p on p.issuer_cik = e.issuer_cik and e.t21 >= p.session_no
        ),
        px_252 as (
            select e.event_id, p.adj_close as a
            from _fe e asof join _fpx p on p.issuer_cik = e.issuer_cik and e.t252 >= p.session_no
        ),
        px_high as (
            select e.event_id, max(p.high_s) as hi, count(*) as n
            from _fe e join _fpx p on p.issuer_cik = e.issuer_cik
             and p.session_no between e.t_no - 251 and e.t_no
            group by 1
        ),
        xbrl as (
            select e.event_id, x.concept,
                   arg_max(x.value, (x.period_end,
                                     -coalesce(date_diff('day', x.period_start, x.period_end), 0)))
                       as v
            from _fe e join core.xbrl_fact x on x.issuer_cik = e.issuer_cik and x.filed <= e.t
             and x.concept in ('equity', 'assets', 'liabilities', 'cash', 'net_income')
            group by 1, 2
        ),
        fin as (
            select event_id,
                   any_value(v) filter (where concept = 'equity') as equity,
                   any_value(v) filter (where concept = 'assets') as assets,
                   any_value(v) filter (where concept = 'liabilities') as liabilities,
                   any_value(v) filter (where concept = 'cash') as cash,
                   any_value(v) filter (where concept = 'net_income') as net_income
            from xbrl group by 1
        )
        select e.event_id,
               px_t.a / px_21.a - 1 as f19,
               px_21.a / px_252.a - 1 as f20,
               case when px_high.n >= 63 then px_t.close_s / nullif(px_high.hi, 0) end as f21,
               coalesce((select min(si.industry) from core.sic_industry si where si.scheme = 12
                         and try_cast(e.g7_sic as INTEGER) between si.sic_from and si.sic_to),
                        'Other') as f24,
               fin.equity / nullif(e.market_cap, 0) as f26,
               cast(fin.net_income < 0 as DOUBLE) as f27,
               coalesce(fin.liabilities, fin.assets - fin.equity) / nullif(fin.assets, 0) as f28,
               fin.cash / nullif(fin.assets, 0) as f29
        from _fe e
        left join px_t using (event_id) left join px_21 using (event_id)
        left join px_252 using (event_id) left join px_high using (event_id)
        left join fin using (event_id)
        """
    )


def build(con: duckdb.DuckDBPyConnection, params: dict) -> FeatureReport:
    """Rebuild `feat.event_features` for every priced event from the labelled-window start."""
    require_tables(con, INPUTS, "labels")
    _events(con, params)
    _insider(con, params)
    _routine(con, params)
    _hit_rate(con, params)
    _market(con)
    con.execute("begin transaction")
    try:
        con.execute(f"create or replace table feat.event_features ({COLUMNS})")
        con.execute(
            """
            insert into feat.event_features
            select e.event_id, e.issuer_cik, e."group", e.t, e.t_session,
                   e.n_entities as f1,
                   e.total_value_usd as f2, i.f3, i.f4, i.f5, i.f6, i.f7, i.f8, r.f9, h.f10,
                   i.f11, i.f12, i.f13, i.f14, i.f15, e.market_cap as f16, e.addv20 as f17,
                   e.total_value_usd / nullif(e.addv20, 0) as f18, k.f19, k.f20, k.f21,
                   e.volatility as f22, e.spread as f23, k.f24,
                   e.total_value_usd / nullif(e.market_cap, 0) as f25, k.f26, k.f27, k.f28,
                   k.f29, coalesce(r.f9_classified, 0), h.f10_history, e.price_source
            from _fe e
            left join _fi i using (event_id) left join _f9 r using (event_id)
            left join _f10 h using (event_id) left join _fk k using (event_id)
            order by e.event_id
            """
        )
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    for name in ("_fe", "_fm", "_fent", "_fi", "_f9", "_f10", "_fk", "_fpx"):
        con.execute(f"drop table if exists {name}")
    report = FeatureReport(
        events=con.execute("select count(*) from feat.event_features").fetchone()[0]
    )
    counts = con.execute(
        "select " + ", ".join(f"count({f})" for f in FEATURES) + " from feat.event_features"
    ).fetchone()
    report.non_null = dict(zip(FEATURES, counts, strict=True))
    return report
