"""`sentinel publish`: `data/serving.duckdb`, the tables the product reads, from the build database
(docs/architecture.md, layer 6). Written to a temporary file and moved into place, so a reader never
sees a half-written file; the app and anyone exploring open it read-only.

- `app.stock`: every company with a page: a price series, periodic reports (US or foreign filer)
  or Form 4 activity; name, ticker, exchange, sector, coverage level, price span.
- `app.price_daily`: the chart: as-traded and adjusted prices, volume and dollar volume per day,
  with the source (Tiingo-derived rows are for private use only, constitution).
- `app.company_card`: the latest feature snapshot per priced company (price, size, volatility,
  financial ratios, events, results timing, insider and short selling), with the last results
  release and the expected next one.
- `app.financials`: each reported financial item per company and period, as first filed.
- `app.filings`: the timeline: every filing of the companies with a page, with 8-K items and link.
- `app.insider_activity`: open-market buys and sells per filing: who, in which role, value,
  shares, holdings before and after, plan and offering flags, link.
- `app.insider_feed`: market-wide insider events (clusters of buyers, senior solo buys).
- `app.screener`: one row per priced company with the screeners' filters.

The risk forecasts and the model card join these once the models exist (plan steps 5 and 8).
"""

import os

import duckdb

from sentinel import db
from sentinel.config import Paths

EDGAR = "https://www.sec.gov/Archives/edgar/data"
NEEDED = ["ref.company", "ref.security", "ref.sector", "core.price_daily", "core.filing",
          "core.financial_fact", "core.results_release", "core.insider_activity",
          "core.insider_cluster", "feature.snapshot"]  # fmt: skip
GROUP_KIND = {"A": "cluster", "B1": "ceo_cfo_buy", "B2": "officer_director_buy"}


def _link(cik: str, accession: str) -> str:
    """SQL: the EDGAR index page of a filing."""
    return (f"'{EDGAR}/' || {cik} || '/' || replace({accession}, '-', '') || '/' || "
            f"{accession} || '-index.htm'")  # fmt: skip


TABLES = {
    "stock": """
        select c.cik, coalesce(s.ticker, c.tickers[1]) as ticker, c.name,
               c.exchanges[1] as exchange, g.sector, c.sic, c.sic_description, c.filer_type,
               coalesce(s.coverage, case c.filer_type when 'us' then 'full'
                        when 'foreign' then 'foreign' else 'price_only' end) as coverage,
               s.security_id is not null as has_prices,
               coalesce(s.listed, c.tickers is not null) as listed, s.source as price_source,
               s.first_session, s.last_session, c.is_fund, c.is_blank_check, c.first_periodic,
               c.last_periodic, c.last_filing, c.is_form4_issuer, c.first_form4, c.last_form4,
               c.former_names
        from b.ref.company c
        left join b.ref.security s on s.security_id = c.cik
        left join b.ref.sector g on g.cik = c.cik
        where s.security_id is not null or c.filer_type <> 'non_reporting' or c.is_form4_issuer
        order by c.cik
    """,
    "price_daily": """
        select cik, session, source, ticker, open, high, low, close, volume, adj_close,
               cum_split_after, dividend, dollar_volume, glitch
        from b.core.price_daily order by cik, session
    """,
    "company_card": """
        with last_release as (
            select cik, max(filing_date) as last_results_date from b.core.results_release
            group by cik
        )
        select s.*, l.last_results_date,
               case when s.days_to_next_results is not null
                    then s.as_of + cast(round(s.days_to_next_results) as INTEGER)
               end as next_results_estimate
        from b.feature.snapshot s left join last_release l using (cik)
        where s.latest order by s.cik
    """,
    "financials": """
        select cik, item, period_start, period_end, period_days, value, unit, filed, known_at,
               form, fp, tag
        from b.core.financial_fact
        where first_filed and cik in (select cik from app.stock)
        order by cik, item, period_end
    """,
    "filings": f"""
        select cik, accession, form, filing_date, report_date, items, known_at,
               {_link("cik", "accession")} as url
        from b.core.filing where cik in (select cik from app.stock)
        order by cik, filing_date, accession
    """,
    "insider_activity": f"""
        select a.issuer_cik as cik, a.accession, a.side, a.filing_date, a.known_at,
               a.min_trade_date, a.max_trade_date, a.owner_names, a.owner_ciks, a.entity_id,
               a.entity_role, a.value_usd, a.shares, a.avg_price, a.planned, a.offering, a.clean,
               a.shares_before, a.shares_after, a.opens_position, a.closes_position,
               {_link("a.issuer_cik", "a.accession")} as url
        from b.core.insider_activity a order by a.issuer_cik, a.filing_date, a.accession
    """,
    "insider_feed": """
        select c.issuer_cik as cik, s.ticker, s.name, c.cluster_date, c.known_at, c.grp,
               case c.grp {kinds} end as kind, c.n_entities, c.total_value_usd, c.top_role,
               c.accessions
        from b.core.insider_cluster c left join app.stock s on s.cik = c.issuer_cik
        where c.starts_event order by c.cluster_date desc, c.issuer_cik
    """,
    "screener": """
        select c.cik, s.ticker, s.name, c.sector, c.coverage, s.listed, c.as_of, c.close,
               c.market_cap, c.vol_63, c.vol_252, c.ret_3m, c.ret_12_1, c.max_drawdown_252,
               c.share_growth_12m, c.cash_runway_years, c.n_offering_12m, c.loss_making,
               c.days_to_next_results, c.next_results_estimate, c.buy_value_12m, c.sell_value_12m,
               c.buyers_14d, c.net_buy_to_mcap_12m, c.short_ratio_1m, c.eligible
        from app.company_card c join app.stock s using (cik)
        order by c.cik
    """,
}


def publish(p: Paths, echo=print) -> dict:
    """Write `serving.duckdb` from the build database; returns rows per table."""
    if not p.build_db.exists():
        raise FileNotFoundError(f"{p.build_db} not found: run `sentinel build` first")
    with db.connect(p, read_only=True) as build:
        db.require(build, NEEDED, "sentinel publish")
    tmp = p.serving_db.with_suffix(".duckdb.tmp")
    tmp.unlink(missing_ok=True)
    kinds = " ".join(f"when '{g}' then '{k}'" for g, k in GROUP_KIND.items())
    counts = {}
    with duckdb.connect(str(tmp), config={"memory_limit": db.MEMORY_LIMIT}) as con:
        con.execute(f"attach '{p.build_db.as_posix()}' as b (read_only)")
        con.execute("create schema app")
        for name, sql in TABLES.items():
            con.execute(f"create table app.{name} as {sql.format(kinds=kinds)}")
            counts[name] = db.count(con, f"app.{name}")
            echo(f"  app.{name}: {counts[name]:,} rows")
        con.execute("detach b")
    os.replace(tmp, p.serving_db)
    return counts
