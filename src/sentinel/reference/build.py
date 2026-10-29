"""Layer 3a: `ref.company`, `ref.ticker_history`, `ref.calendar`, `ref.sector`.

- `ref.company`: every company-like SEC filer and every Form 4 issuer: names, SIC, `filer_type`
  (`us`: a 10-K or 10-Q since 2012; `foreign`: only 20-F or 40-F; `non_reporting`: neither, such as
  foreign companies whose shares trade over the counter in the US), `is_fund` (a registered fund's
  report, N-CSR, NPORT or N-CEN, since 2012, or a fund SIC; v5 rule), `is_blank_check` (SIC 6770),
  the span of its periodic reports and filings, whether it is a Form 4 issuer, today's tickers.
- `ref.ticker_history`: which company used which ticker when, from two kinds of SEC evidence: the
  symbol printed on its own Form 4s (from the first to the last filing that printed it) and the
  SEC's daily ticker lists (from the first to the last list naming it; still listed: open-ended).
  Prices matched to a company later add their own spans in `core.price_choice`.
- `ref.calendar`: the market's trading days (SPY's sessions on Yahoo), numbered.
- `ref.sector`: each company's Fama-French 12 sector from its current SIC ("Other" if none).
"""

import re
from datetime import date

import duckdb

from sentinel import db
from sentinel.config import Paths, sources

SINCE = date(2012, 1, 1)
NO_TICKER = {"", "NONE", "NA", "NULL", "N/A"}
MARKET_TICKERS = 1000  # a session at least this many tickers reached is a market session
US_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-KT/A")
FOREIGN_FORMS = ("20-F", "20-F/A", "40-F", "40-F/A")
FILER_FORMS = (*US_FORMS, *FOREIGN_FORMS, "8-K", "6-K")


def normalise(ticker: str | None) -> str | None:
    """Upper case, `.` and `/` become `-`, stray characters dropped; placeholders → None (v1)."""
    t = (ticker or "").strip().upper()
    if re.sub(r"[^A-Z0-9]", "", t) in NO_TICKER:
        return None
    t = re.sub(r"[^A-Z0-9./-]", "", t).replace(".", "-").replace("/", "-").strip("-")
    return t or None


def split_symbols(raw: str | None) -> list[str]:
    """Normalised tickers in a Form 4 `ISSUERTRADINGSYMBOL`, which may list classes ("XA, XB")."""
    return [t for part in re.split(r"[,;]", raw or "") if (t := normalise(part))]


def _sql_list(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def build_company(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    needed = ["stg_sec_filings.filer", "stg_sec_filings.filing", "stg_sec_form4.submission",
              "stg_sec_tickers.snapshot"]  # fmt: skip
    db.require(con, needed, "ref.company")
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table ref.company as
            with f as (
                select cik,
                       bool_or(form in ({_sql_list(US_FORMS)}) and filing_date >= $since) as us,
                       bool_or(form in ({_sql_list(FOREIGN_FORMS)}) and filing_date >= $since)
                           as foreign_reports,
                       bool_or((form like 'N-CSR%' or form like 'NPORT%' or form like 'N-CEN%')
                               and filing_date >= $since) as fund_reports,
                       min(filing_date) filter (where form in
                           ({_sql_list(US_FORMS + FOREIGN_FORMS)}) and filing_date >= $since)
                           as first_periodic,
                       max(filing_date) filter (where form in
                           ({_sql_list(US_FORMS + FOREIGN_FORMS)})) as last_periodic,
                       max(filing_date) filter (where form in ({_sql_list(FILER_FORMS)}))
                           as last_filing
                from stg_sec_filings.filing group by cik
            ),
            form4 as (
                select issuercik as cik, count(distinct accession_number) as n_form4,
                       min(filing_date) as first_form4, max(filing_date) as last_form4
                from stg_sec_form4.submission where issuercik is not null group by 1
            ),
            today as (
                select cik, list(ticker order by rank) as tickers,
                       list(exchange order by rank) as exchanges
                from stg_sec_tickers.snapshot
                where snapshot_date = (select max(snapshot_date) from stg_sec_tickers.snapshot)
                group by cik
            )
            select fl.cik, fl.name, fl.former_names, fl.entity_type, fl.sic, fl.sic_description,
                   fl.category, fl.state_of_incorporation, fl.fiscal_year_end,
                   case when f.us then 'us' when f.foreign_reports then 'foreign'
                        else 'non_reporting' end as filer_type,
                   coalesce(f.fund_reports, false)
                       or coalesce(try_cast(fl.sic as INTEGER) in (6722, 6726), false) as is_fund,
                   coalesce(try_cast(fl.sic as INTEGER) = 6770, false) as is_blank_check,
                   f.first_periodic, f.last_periodic, f.last_filing,
                   coalesce(form4.n_form4, 0) > 0 as is_form4_issuer, form4.first_form4,
                   form4.last_form4, today.tickers, today.exchanges
            from stg_sec_filings.filer fl
            left join f using (cik) left join form4 using (cik) left join today using (cik)
            where fl.is_company or form4.cik is not null
            """,
            {"since": SINCE},
        )
    counts = dict(zip(["company", "us", "foreign", "non_reporting", "funds"], con.execute(
        "select count(*), count(*) filter (where filer_type = 'us'), "
        "count(*) filter (where filer_type = 'foreign'), "
        "count(*) filter (where filer_type = 'non_reporting'), count(*) filter (where is_fund) "
        "from ref.company").fetchone(), strict=True))  # fmt: skip
    echo(f"  companies: {counts}")
    return counts


def build_ticker_history(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["stg_sec_form4.submission", "stg_sec_tickers.snapshot"], "ref.ticker_history")
    spans: dict[tuple[str, str], list] = {}
    for cik, raw, first, last in con.execute(
        "select issuercik, issuertradingsymbol, min(filing_date), max(filing_date) "
        "from stg_sec_form4.submission where issuercik is not null and filing_date is not null "
        "and issuertradingsymbol is not null group by all"
    ).fetchall():
        for ticker in split_symbols(raw):
            span = spans.setdefault((cik, ticker), [first, last])
            span[0], span[1] = min(span[0], first), max(span[1], last)
    rows = [(cik, t, None, a, b, "form4") for (cik, t), (a, b) in spans.items()]
    latest = con.execute("select max(snapshot_date) from stg_sec_tickers.snapshot").fetchone()[0]
    listed: dict[tuple[str, str], list] = {}
    for cik, ticker, exchange, first, last in con.execute(
        "select cik, ticker, arg_max(exchange, snapshot_date), min(snapshot_date), "
        "max(snapshot_date) from stg_sec_tickers.snapshot group by cik, ticker"
    ).fetchall():
        if t := normalise(ticker):
            listed[(cik, t)] = [first, None if last == latest else last, exchange]
    rows += [(cik, t, ex, a, b, "sec_list") for (cik, t), (a, b, ex) in listed.items()]
    with db.transaction(con):
        con.execute(
            "create or replace table ref.ticker_history (cik VARCHAR, ticker VARCHAR, "
            "exchange VARCHAR, valid_from DATE, valid_to DATE, evidence VARCHAR)"
        )
        con.executemany("insert into ref.ticker_history values (?, ?, ?, ?, ?, ?)", rows)
    counts = {"ticker_history": len(rows), "form4": len(spans), "sec_list": len(listed)}
    echo(f"  ticker history: {counts}")
    return counts


def build_calendar(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """SPY's sessions since `prices.history_start`. Fails when SPY's prices stop before the last
    session most tickers reached: an old SPY file would silently drop every later price (the
    calendar stopped on 23 October 2026 that way; specs/001-daily-data-refresh, research R9)."""
    db.require(con, ["stg_yahoo.price"], "ref.calendar")
    start = sources(p)["prices"]["history_start"]
    n, spy_last = con.execute(
        "select count(distinct session), max(session) from stg_yahoo.price where ticker = 'SPY' "
        "and session >= ?", [start]).fetchone()  # fmt: skip
    if not n:
        raise db.MissingInput("ref.calendar needs SPY's Yahoo prices: run `sentinel fetch yahoo`")
    market_last = con.execute(
        "select max(session) from (select session from stg_yahoo.price group by session "
        "having count(distinct ticker) >= ?)", [MARKET_TICKERS]).fetchone()[0]  # fmt: skip
    if market_last is not None and spy_last < market_last:
        raise db.StepFailed(f"SPY's prices end on {spy_last} but at least {MARKET_TICKERS:,} "
                            f"tickers reach {market_last}: fetch Yahoo again")  # fmt: skip
    with db.transaction(con):
        con.execute(
            """
            create or replace table ref.calendar as
            select session, cast(row_number() over (order by session) as INTEGER) as session_no
            from (select distinct session from stg_yahoo.price
                  where ticker = 'SPY' and session >= ? and close is not null)
            """,
            [start],
        )
    echo(f"  calendar: {n:,} sessions")
    return {"calendar": n}


def build_sector(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["ref.company", "stg_market.sic_industry"], "ref.sector")
    with db.transaction(con):
        con.execute(
            """
            create or replace table ref.sector as
            select c.cik, c.sic, coalesce(
                       (select min(s.industry) from stg_market.sic_industry s where s.scheme = 12
                          and try_cast(c.sic as INTEGER) between s.sic_from and s.sic_to),
                       'Other') as sector
            from ref.company c
            """
        )
    n = db.count(con, "ref.sector")
    echo(f"  sectors: {n:,}")
    return {"sector": n}
