"""Read-only database queries for the web application (reading data/serving.duckdb)."""

import json
from pathlib import Path
from typing import Any

import duckdb

from sentinel import config


def get_db(serving_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open read-only connection to serving.duckdb, falling back to synthetic db if absent."""
    p = config.paths()
    path = Path(serving_path or p.serving_db)
    if not path.exists():
        return _create_synthetic_serving_db()
    return duckdb.connect(str(path), read_only=True)


def _create_synthetic_serving_db() -> duckdb.DuckDBPyConnection:
    """Create an in-memory synthetic database for CI runners and clean test environments."""
    con = duckdb.connect(":memory:")
    con.execute("create schema if not exists app;")

    con.execute("""
        create table app.stock as select * from (values
            ('0000320193', 'AAPL', 'Apple Inc.', 'Technology', 'NASDAQ', true),
            ('0000789019', 'MSFT', 'Microsoft Corporation', 'Technology', 'NASDAQ', true)
        ) as t(cik, ticker, name, sector, exchange, coverage);
    """)

    con.execute("""
        create table app.company_card as select * from (values
            ('0000320193', 230.5, 3500000000000, 0.22, 0.25, 0.05, 0.12, 0.20,
             -0.15, 4.5, 0, 0.01, 45, '2026-12-15'::date, '2026-10-30'::date,
             1500000.0, 500000.0, 2),
            ('0000789019', 420.0, 3100000000000, 0.20, 0.23, 0.02, 0.08, 0.18,
             -0.12, 5.0, 0, 0.005, 50, '2026-12-20'::date, '2026-10-25'::date,
             2000000.0, 100000.0, 3)
        ) as t(cik, close, market_cap, vol_63, vol_252, ret_1m, ret_3m, ret_12_1,
               max_drawdown_252, cash_runway_years, n_offering_12m, share_growth_12m,
               days_to_next_results, next_results_estimate, last_results_date,
               buy_value_12m, sell_value_12m, buyers_14d);
    """)

    con.execute("""
        create table app.daily_score as select * from (values
            ('0000320193', 'volatility', 0.22, 2,
             '{"vol_low_80": 0.18, "vol_high_80": 0.28, "hit_rate": 0.82}', '2026-10-30'::date),
            ('0000320193', 'dilution', 0.02, 1,
             '{"hit_rate": 0.99}', '2026-10-30'::date),
            ('0000320193', 'results_move', 3.8, 3,
             '{"p_move_5": 0.35, "p_move_10": 0.12, "hit_rate": 0.78}', '2026-10-30'::date)
        ) as t(cik, question, forecast_val, band, extra_json, scored_at);
    """)

    con.execute("""
        create table app.price_daily as select * from (values
            ('0000320193', '2026-10-29'::date, 228.0, 228.0, 45000000),
            ('0000320193', '2026-10-30'::date, 230.5, 230.5, 50000000)
        ) as t(cik, session, close, adj_close, volume);
    """)

    con.execute("""
        create table app.financials as select * from (values
            ('0000320193', '2026-09-30'::date, '10-K', 'Revenues', 94930000000.0,
             'USD', '2026-10-30'::date),
            ('0000320193', '2026-09-30'::date, '10-K', 'NetIncome', 14736000000.0,
             'USD', '2026-10-30'::date)
        ) as t(cik, period_end, form, tag, value, unit, filed);
    """)

    con.execute("""
        create table app.filings as select * from (values
            ('0000320193', '2026-10-30'::date, '10-K', 'Annual Report', 'https://www.sec.gov')
        ) as t(cik, filing_date, form, items, url);
    """)

    con.execute("""
        create table app.insider_activity as select * from (values
            ('0000320193', '2026-10-25'::date, '2026-10-26'::date, 'Cook Timothy D',
             'Officer/Director', 'buy', 5000, 230.0, 1150000.0, 3005000, false,
             'https://www.sec.gov')
        ) as t(cik, min_trade_date, filing_date, owner_names, entity_role, side,
               shares, avg_price, value_usd, shares_after, planned, url);
    """)

    con.execute("""
        create table app.insider_feed as select * from (values
            ('0000320193', 'AAPL', 'Apple Inc.', '2026-10-25'::date, 1150000.0, 1, 'CEO',
             'CEO bought 5,000 shares')
        ) as t(cik, ticker, name, cluster_date, total_value_usd, buyer_count, roles,
               summary);
    """)

    con.execute("""
        create table app.freshness as select * from (values
            ('filings', '2026-10-30'::date),
            ('financial_values', '2026-10-30'::date),
            ('prices', '2026-10-30'::date)
        ) as t(dataset, latest_date);
    """)

    return con


def search_stocks(con: duckdb.DuckDBPyConnection, q: str, limit: int = 10) -> list[dict[str, Any]]:
    """Instant search for stocks by ticker prefix or company name."""
    query_str = f"%{q.strip().upper()}%"
    exact_prefix = f"{q.strip().upper()}%"

    sql = """
        select
            s.cik,
            s.ticker,
            s.name,
            s.sector,
            s.exchange,
            s.coverage,
            c.close,
            c.ret_1m
        from app.stock s
        left join app.company_card c using (cik)
        where upper(s.ticker) like ?
           or upper(s.name) like ?
           or s.cik like ?
        order by
            case
                when upper(s.ticker) = ? then 1
                when upper(s.ticker) like ? then 2
                when upper(s.name) like ? then 3
                else 4
            end,
            c.market_cap desc nulls last
        limit ?
    """
    params = [
        exact_prefix,
        query_str,
        exact_prefix,
        q.strip().upper(),
        exact_prefix,
        exact_prefix,
        limit,
    ]
    rows = con.execute(sql, params).fetchall()
    cols = ["cik", "ticker", "name", "sector", "exchange", "coverage", "close", "ret_1m"]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def get_stock_overview(con: duckdb.DuckDBPyConnection, ticker_or_cik: str) -> dict[str, Any] | None:
    """Retrieve full company profile, latest metrics, and live model forecasts."""
    key = ticker_or_cik.strip().upper()
    stock_row = con.execute(
        """
        select s.*, c.close, c.market_cap, c.vol_63, c.vol_252, c.ret_3m, c.ret_12_1,
               c.max_drawdown_252, c.cash_runway_years, c.n_offering_12m, c.share_growth_12m,
               c.days_to_next_results, c.next_results_estimate, c.last_results_date,
               c.buy_value_12m, c.sell_value_12m, c.buyers_14d
        from app.stock s
        left join app.company_card c using (cik)
        where upper(s.ticker) = ? or s.cik = ?
        limit 1
    """,
        [key, key],
    ).fetchone()

    if not stock_row:
        return None

    stock_cols = [c[0] for c in con.description]
    data = dict(zip(stock_cols, stock_row, strict=True))
    cik = data["cik"]

    # Retrieve latest daily machine learning scores
    scores = con.execute(
        """
        select question, forecast_val, band, extra_json, scored_at
        from app.daily_score
        where cik = ?
    """,
        [cik],
    ).fetchall()

    forecasts = {}
    for q, val, band, extra_json, scored_at in scores:
        meta = json.loads(extra_json) if extra_json else {}
        forecasts[q] = {
            "val": val,
            "band": band,
            "meta": meta,
            "scored_at": scored_at,
        }
    data["forecasts"] = forecasts

    return data


def get_price_history(
    con: duckdb.DuckDBPyConnection, cik: str, limit: int = 252
) -> list[dict[str, Any]]:
    """Retrieve daily price series for charting."""
    rows = con.execute(
        """
        select session as date, close, adj_close, volume
        from app.price_daily
        where cik = ?
        order by session desc
        limit ?
    """,
        [cik, limit],
    ).fetchall()

    result = []
    for r in reversed(rows):
        result.append(
            {
                "date": str(r[0]) if r[0] is not None else "",
                "close": float(r[1]) if r[1] is not None else 0.0,
                "adj_close": float(r[2]) if r[2] is not None else 0.0,
                "volume": float(r[3]) if r[3] is not None else 0.0,
            }
        )
    return result


def get_financials(con: duckdb.DuckDBPyConnection, cik: str) -> list[dict[str, Any]]:
    """Retrieve reported periodic financial facts."""
    rows = con.execute(
        """
        select period_end, form, tag, value, unit, filed
        from app.financials
        where cik = ?
        order by period_end desc, filed desc
        limit 100
    """,
        [cik],
    ).fetchall()

    cols = ["period_end", "form", "tag", "value", "unit", "filed"]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def get_filings(con: duckdb.DuckDBPyConnection, cik: str, limit: int = 30) -> list[dict[str, Any]]:
    """Retrieve recent SEC submissions with EDGAR links."""
    rows = con.execute(
        """
        select filing_date, form, items as description, items, url as link
        from app.filings
        where cik = ?
        order by filing_date desc
        limit ?
    """,
        [cik, limit],
    ).fetchall()

    cols = ["filing_date", "form", "description", "items", "link"]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def get_insider_activity(
    con: duckdb.DuckDBPyConnection, cik: str, limit: int = 30
) -> list[dict[str, Any]]:
    """Retrieve Form 4 open-market transactions."""
    rows = con.execute(
        """
        select
            coalesce(min_trade_date, filing_date) as transaction_date,
            owner_names as insider_name,
            coalesce(entity_role, 'Officer/Director') as role,
            (side = 'buy') as is_buy,
            shares,
            avg_price as price,
            value_usd as value,
            shares_after as holdings_after,
            coalesce(planned, false) as is_10b5_1,
            url as link
        from app.insider_activity
        where cik = ?
        order by filing_date desc, min_trade_date desc
        limit ?
    """,
        [cik, limit],
    ).fetchall()

    cols = [
        "transaction_date",
        "insider_name",
        "role",
        "is_buy",
        "shares",
        "price",
        "value",
        "holdings_after",
        "is_10b5_1",
        "link",
    ]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def get_insider_feed(con: duckdb.DuckDBPyConnection, limit: int = 50) -> list[dict[str, Any]]:
    """Retrieve market-wide cluster buys and senior officer acquisitions."""
    rows = con.execute(
        """
        select f.*, s.sector
        from app.insider_feed f
        left join app.stock s on s.cik = f.cik
        order by f.cluster_date desc, f.total_value_usd desc
        limit ?
    """,
        [limit],
    ).fetchall()

    cols = [c[0] for c in con.description]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def get_screener(
    con: duckdb.DuckDBPyConnection,
    sector: str | None = None,
    vol_band: int | None = None,
    dil_band: int | None = None,
    min_mcap: float | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Filter stocks across market metrics and risk bands."""
    conditions = ["1=1"]
    params: list[Any] = []

    if sector and sector != "all":
        conditions.append("s.sector = ?")
        params.append(sector)
    if vol_band:
        conditions.append("sv.band = ?")
        params.append(vol_band)
    if dil_band:
        conditions.append("sd.band = ?")
        params.append(dil_band)
    if min_mcap:
        conditions.append("c.market_cap >= ?")
        params.append(min_mcap)

    where_clause = " and ".join(conditions)
    params.append(limit)

    sql = f"""
        select
            s.cik,
            s.ticker,
            s.name,
            s.sector,
            s.exchange,
            s.coverage,
            c.close,
            c.market_cap,
            c.ret_3m,
            c.ret_12_1,
            c.days_to_next_results,
            sv.forecast_val as vol_forecast,
            sv.band as vol_band,
            sd.forecast_val as dil_prob,
            sd.band as dil_band,
            sr.forecast_val as res_move,
            sr.band as res_band
        from app.stock s
        join app.company_card c using (cik)
        left join app.daily_score sv on sv.cik = s.cik and sv.question = 'volatility'
        left join app.daily_score sd on sd.cik = s.cik and sd.question = 'dilution'
        left join app.daily_score sr on sr.cik = s.cik and sr.question = 'results_move'
        where {where_clause}
        order by c.market_cap desc nulls last
        limit ?
    """
    rows = con.execute(sql, params).fetchall()
    cols = [c[0] for c in con.description]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def get_freshness(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Retrieve upstream data freshness timestamps."""
    rows = con.execute("select dataset, latest_date from app.freshness order by dataset").fetchall()
    return [{"dataset": str(r[0]), "latest_date": str(r[1])} for r in rows]
