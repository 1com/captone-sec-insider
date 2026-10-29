"""Layer 3b: macro observations, dated ticker spans and short volume per company.

- `core.macro_observation`: every FRED series and the VIX close in one long table, with
  `known_at`, the first trading day on or after the value became public (`stg_market`: market
  series and the VIX on their own date, CPI and unemployment on their first-release day).
- `core.ticker_span`: which company traded under which symbol when, for data keyed by symbol
  (FINRA). v1's rules: a ticker runs from the first to the last Form 4 that printed it; a ticker
  listed today runs to date, starting where the company's Form 4 tickers end; a company with
  neither uses its price series' ticker over the series; and each company's earliest ticker
  reaches back to the day after another company last used the symbol (so a renamed company is not
  credited with another company's trades, and the years before its first Form 4 are covered).
- `core.short_volume`: FINRA's daily short and total (off-exchange) volume per company, summed
  over the symbols it traded under that day.
"""

from datetime import date, timedelta

import duckdb

from sentinel import db
from sentinel.config import Paths
from sentinel.reference.build import normalise

EARLIEST = date(1900, 1, 1)  # a span with no earlier user of its symbol


def build_macro(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["stg_market.fred", "stg_market.vix", "ref.calendar"],
               "core.macro_observation")  # fmt: skip
    with db.transaction(con):
        con.execute(
            """
            create or replace table core.macro_observation as
            with o as (
                select series, mode, period, value, available from stg_market.fred
                union all
                select 'VIX', 'market', session, close, session from stg_market.vix
            )
            select o.series, o.mode, o.period, o.value, o.available,
                   case when o.available < (select min(session) from ref.calendar)
                        then o.available else c.session end as known_at
            from o asof left join ref.calendar c on c.session >= o.available
            order by o.series, o.period
            """
        )
    counts = dict(
        con.execute(
            "select series, count(*) from core.macro_observation group by 1 order by 1"
        ).fetchall()
    )
    echo(f"  macro observations: {counts}")
    return {"series": len(counts), "observations": sum(counts.values())}


def ticker_spans(form4, listed, series) -> list[tuple]:
    """(cik, ticker, valid_from, valid_to, evidence) by the rules in the module docstring.

    `form4`: (cik, ticker, first, last) Form 4 spans; `listed`: (cik, ticker, snapshot date) of the
    tickers listed today; `series`: (cik, ticker, first session, last session, source) of the
    chosen price series. A missing `valid_to` means to date."""
    spans: dict[tuple[str, str], list] = {(c, t): [a, b, "form4"] for c, t, a, b in form4}
    ends: dict[str, date] = {}
    for (cik, _), (_, last, _) in spans.items():
        ends[cik] = max(ends.get(cik, last), last)
    price = {cik: (t, a, b, src) for cik, t, a, b, src in series if t}
    for cik, ticker, snapshot in listed:
        if (cik, ticker) in spans:
            spans[(cik, ticker)][1] = None
            continue
        own = price.get(cik)
        start = ends.get(cik) or (own[1] if own and own[0] == ticker else snapshot)
        spans[(cik, ticker)] = [start, None, "listed"]
    known = {cik for cik, _ in spans}
    for cik, (ticker, first, last, source) in price.items():
        if cik not in known:
            spans[(cik, ticker)] = [first, None if source == "yahoo" else last, "price_series"]
    users: dict[str, list[tuple[str, date, date | None]]] = {}
    earliest: dict[str, tuple[str, str]] = {}
    for (cik, ticker), (start, end, _) in spans.items():
        users.setdefault(ticker, []).append((cik, start, end))
        if cik not in earliest or start < spans[earliest[cik]][0]:
            earliest[cik] = (cik, ticker)
    for cik, key in earliest.items():
        start = spans[key][0]
        others = [min(e or start, start) for c, s, e in users[key[1]] if c != cik and s < start]
        spans[key][0] = min(start, max(others) + timedelta(days=1)) if others else EARLIEST
    return sorted((c, t, a, b, ev) for (c, t), (a, b, ev) in spans.items())


def build_ticker_span(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["ref.ticker_history", "ref.security"], "core.ticker_span")
    form4 = con.execute(
        "select cik, ticker, valid_from, valid_to from ref.ticker_history where evidence = 'form4'"
    ).fetchall()
    listed = con.execute(
        "select cik, ticker, valid_from from ref.ticker_history "
        "where evidence = 'sec_list' and valid_to is null"
    ).fetchall()
    series = [
        (cik, normalise(t), a, b, src)
        for cik, t, a, b, src in con.execute(
            "select security_id, ticker, first_session, last_session, source from ref.security"
        ).fetchall()
    ]
    rows = ticker_spans(form4, listed, series)
    with db.transaction(con):
        con.execute(
            "create or replace table core.ticker_span (cik VARCHAR, ticker VARCHAR, "
            "valid_from DATE, valid_to DATE, evidence VARCHAR)"
        )
        con.executemany("insert into core.ticker_span values (?, ?, ?, ?, ?)", rows)
    counts = {"spans": len(rows), "companies": len({r[0] for r in rows})}
    echo(f"  ticker spans: {counts}")
    return counts


def build_short_volume(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["stg_market.short_volume", "core.ticker_span"], "core.short_volume")
    with db.transaction(con):
        con.execute(
            """
            create or replace table core.short_volume as
            with v as (
                select session, short_volume, total_volume,
                       regexp_replace(replace(replace(upper(trim(symbol)), '.', '-'), '/', '-'),
                                      '[^A-Z0-9-]', '', 'g') as ticker
                from stg_market.short_volume
            )
            select s.cik, v.session, sum(v.short_volume) as short_volume,
                   sum(v.total_volume) as total_volume, count(*) as n_symbols
            from v join core.ticker_span s
              on s.ticker = v.ticker
             and v.session between s.valid_from and coalesce(s.valid_to, DATE '9999-12-31')
            group by s.cik, v.session
            order by s.cik, v.session
            """
        )
    rows, companies = con.execute(
        "select count(*), count(distinct cik) from core.short_volume"
    ).fetchone()
    counts = {"company_days": rows, "companies": companies}
    echo(f"  short volume: {counts}")
    return counts
