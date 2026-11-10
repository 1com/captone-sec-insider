"""Read-only queries of the serving copy (`data/serving.duckdb`) for the stock research app (026).

Every request opens its own read-only connection (capped at `db.MEMORY_LIMIT`) and closes it, so
the daily update can swap in the next day's copy at any time. A missing or unreadable copy raises
`NoData`: the app then shows an error, never invented values (FR-019)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from sentinel import db
from sentinel.web import glossary


class NoData(RuntimeError):
    """The serving copy is missing or cannot be read."""


@contextmanager
def connect(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    if not path.exists():
        raise NoData(
            f"The data file {path.name} does not exist yet: run `sentinel publish` or wait for "
            "the daily update."
        )
    try:
        con = duckdb.connect(str(path), read_only=True, config={"memory_limit": db.MEMORY_LIMIT})
    except duckdb.Error as e:
        raise NoData(f"The data file {path.name} cannot be read right now: {e}") from e
    try:
        yield con
    finally:
        con.close()


def _plain(v):
    """A JSON value: dates as ISO text, NaN as None."""
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "item"):  # numpy scalars
        return _plain(v.item())
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _rows(con, sql: str, args: list | None = None) -> list[dict]:
    cur = con.execute(sql, args or [])
    cols = [d[0] for d in cur.description]
    return [{c: _plain(v) for c, v in zip(cols, row, strict=True)} for row in cur.fetchall()]


def _one(con, sql: str, args: list | None = None) -> dict | None:
    rows = _rows(con, sql, args)
    return rows[0] if rows else None


def freshness(con) -> dict:
    """Per source the date it is current to (FR-014), read from the data."""
    out = {r["dataset"]: r["latest_date"] for r in _rows(con, "select * from app.freshness")}
    return {
        "prices": out.get("prices"),
        "filings": out.get("filings"),
        "insider_filings": out.get("insider_filings"),
        "short_volume": out.get("short_volume"),
        "financials": out.get("financial_values"),
    }


def search(con, q: str, limit: int = 12) -> list[dict]:
    """Companies by ticker (exact, then prefix) or name (current or former); one line per company,
    the listed ones first (FR-001)."""
    q = q.strip()
    if not q:
        return []
    return _rows(
        con,
        """
        with s as (
            select cik, ticker, name, exchange, listed, first_session, last_session,
                case when upper(ticker) = upper($q) then 0
                     when upper(ticker) like upper($q) || '%' then 1
                     when name ilike $q || '%' then 2
                     when name ilike '%' || $q || '%' then 3
                     when coalesce(former_names::varchar, '') ilike '%' || $q || '%' then 4
                end as rank
            from app.stock
        )
        select cik, ticker, name, exchange, listed, first_session, last_session from s
        where rank is not null
        qualify row_number() over (partition by cik
                                   order by rank, listed desc, last_session desc nulls last) = 1
        order by rank, listed desc, last_session desc nulls last, ticker
        limit $n
        """,
        {"q": q, "n": limit},
    )


def company(con, cik: str) -> dict | None:
    """The company's facts, tickers, latest feature row and quote (FR-002)."""
    tickers = _rows(
        con,
        "select ticker, exchange, listed, first_session, last_session, price_source "
        "from app.stock where cik = ? order by listed desc, last_session desc nulls last",
        [cik],
    )
    if not tickers:
        return None
    facts = _one(
        con,
        "select name, sector, sic, sic_description, filer_type, coverage, is_fund, "
        "is_blank_check, array_to_string(list_transform(former_names, x -> x.name), '; ') "
        "as former_names, has_prices, listed, "
        "price_source, first_session, last_session, first_periodic, last_periodic, last_filing, "
        "is_form4_issuer, first_form4, last_form4 from app.stock where cik = ? "
        "order by listed desc, last_session desc nulls last limit 1",
        [cik],
    )
    card = _one(con, "select * from app.company_card where cik = ?", [cik]) or {}
    quote = _one(
        con,
        """
        with p as (
            select session, close / cum_split_after as c, high / cum_split_after as h,
                   low / cum_split_after as l, volume * cum_split_after as v,
                   row_number() over (order by session desc) as k
            from app.price_daily
            where cik = ? and not coalesce(glitch, false) and close > 0
        )
        select max(session) filter (where k = 1) as session,
               max(c) filter (where k = 1) as close, max(c) filter (where k = 2) as previous,
               max(h) filter (where k <= 252) as high_52w,
               min(l) filter (where k <= 252) as low_52w,
               avg(v) filter (where k <= 20) as volume_20d, count(*) as sessions
        from p
        """,
        [cik],
    )
    return {"cik": cik, "tickers": tickers, "facts": facts, "card": card, "quote": quote}


def prices(con, cik: str) -> dict:
    """Daily prices and volumes, adjusted for splits, glitch days left out (FR-006)."""
    rows = con.execute(
        "select session, open / cum_split_after, high / cum_split_after, low / cum_split_after, "
        "close / cum_split_after, volume * cum_split_after, source from app.price_daily "
        "where cik = ? and not coalesce(glitch, false) and close > 0 order by session",
        [cik],
    ).fetchall()
    keys = ("t", "o", "h", "l", "c", "v", "source")
    out = {k: [] for k in keys}
    for row in rows:
        for k, v in zip(keys, row, strict=True):
            out[k].append(_plain(round(v, 6) if isinstance(v, float) else v))
    out["sources"] = sorted(set(out.pop("source")))
    return out


def insiders(con, cik: str) -> dict:
    """Form 4 filings: monthly values bought and sold, clusters, and every filing (FR-008, -009)."""
    trades = _rows(
        con,
        "select filing_date, coalesce(max_trade_date, min_trade_date, filing_date) as trade_date, "
        "side, array_to_string(owner_names, ', ') as owner, entity_role as role, shares, "
        "avg_price, value_usd, "
        "planned, offering, url from app.insider_activity where cik = ? "
        "order by filing_date desc, trade_date desc",
        [cik],
    )
    monthly = _rows(
        con,
        """
        select date_trunc('month', coalesce(max_trade_date, min_trade_date, filing_date)) as month,
               sum(value_usd) filter (where side = 'buy') as bought,
               sum(value_usd) filter (where side = 'sell') as sold,
               sum(value_usd) filter (where side = 'sell' and not coalesce(planned, false))
                   as sold_unplanned,
               count(distinct entity_id) filter (where side = 'buy') as buyers,
               count(distinct entity_id) filter (where side = 'sell') as sellers
        from app.insider_activity where cik = ? group by 1 order by 1
        """,
        [cik],
    )
    clusters = _rows(
        con,
        "select cluster_date, kind, n_entities, total_value_usd, top_role from app.insider_feed "
        "where cik = ? order by cluster_date",
        [cik],
    )
    return {"trades": trades, "monthly": monthly, "clusters": clusters}


def filings(con, cik: str, kind: str | None = None, limit: int = 200) -> dict:
    """The company's filings, newest first, explained in plain English; counts per kind (FR-010)."""
    forms = con.execute(
        "select form, count(*) from app.filings where cik = ? group by 1", [cik]
    ).fetchall()
    kind_of = {f: glossary.describe_form(f)["kind"] for f, _ in forms}
    counts = {k: 0 for k in glossary.KINDS}
    for f, n in forms:
        counts[kind_of[f]] += n
    chosen = [f for f, _ in forms if kind is None or kind_of[f] == kind]
    rows = []
    if chosen:
        rows = _rows(
            con,
            "select form, filing_date, report_date, items, url from app.filings "
            "where cik = ? and form in (select unnest(?::varchar[])) "
            "order by filing_date desc, accession desc limit ?",
            [cik, chosen, limit],
        )
    for r in rows:
        r["about"] = glossary.describe_form(r["form"])
        r["item_list"] = glossary.describe_items(r.pop("items"))
    total = sum(n for f, n in forms if f in chosen)
    return {"counts": counts, "total": total, "filings": rows}


def offerings(con, cik: str) -> list[dict]:
    """Filings that signal new shares, for the chart's markers (FR-007)."""
    rows = _rows(
        con,
        "select form, filing_date, items from app.filings where cik = ? order by filing_date",
        [cik],
    )
    out = []
    for r in rows:
        about = glossary.describe_form(r["form"])
        items = [i for i in glossary.describe_items(r["items"]) if i["dilution_signal"]]
        if (about["dilution_signal"] and not about["amendment"]) or items:
            label = items[0]["name"] if items and not about["dilution_signal"] else about["name"]
            out.append({"date": r["filing_date"], "form": r["form"], "label": label})
    return out


def shares(con, cik: str) -> list[dict]:
    """Shares outstanding as first filed per period, adjusted for later splits (FR-003)."""
    return _rows(
        con,
        """
        with s as (
            select period_end, value, filed from app.financials
            where cik = ? and item = 'shares_outstanding' and value > 0
            qualify row_number() over (partition by period_end order by filed, value) = 1
        ),
        p as (select session, cum_split_after from app.price_daily where cik = ?),
        first as (select cum_split_after as f from p order by session limit 1)
        select s.period_end, s.filed, s.value as reported,
               s.value * coalesce(p.cum_split_after, (select f from first), 1) as adjusted
        from s asof left join p on p.session <= s.period_end
        order by s.period_end
        """,
        [cik, cik],
    )


def diagnostics(con, cik: str) -> dict:
    """The data behind the page (FR-015, first part)."""
    prices_ = _one(
        con,
        "select min(session) as first, max(session) as last, count(*) as days, "
        "count(*) filter (where glitch) as glitch_days, "
        "string_agg(distinct source, ', ') as sources from app.price_daily where cik = ?",
        [cik],
    )
    last = _rows(
        con,
        "select form, max(filing_date) as last, count(*) as n from app.filings where cik = ? "
        "and form in ('10-K', '10-Q', '8-K', '20-F', '6-K', '4', 'DEF 14A', 'S-1', 'S-3') "
        "group by 1 order by 2 desc",
        [cik],
    )
    n_filings = con.execute("select count(*) from app.filings where cik = ?", [cik]).fetchone()[0]
    n_insider = con.execute(
        "select count(*) from app.insider_activity where cik = ?", [cik]
    ).fetchone()[0]
    return {
        "prices": prices_,
        "last_filings": last,
        "filings": n_filings,
        "insider_filings": n_insider,
        "freshness": freshness(con),
    }
