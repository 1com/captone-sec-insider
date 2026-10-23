"""Step 8: how each early-ending price series ended (feature 004, research R11; plan §6.7).

A chosen series ends early when its last session is more than `rules.delisting_end_gap_sessions`
before the data's last session. Its class comes from SEC filing evidence, in this order:
1. `remap`: a 10-Q or 10-K filed more than `rules.remap_after_days` after the last price — likely
   a ticker change, not a delisting; without a new series it takes the unknown return;
2. `acquired`: a merger form in the `registered.merger_lookback` months before the last trade;
3. `performance`: a delisting or deregistration form from 12 months before to
   `rules.delisting_notice_after_months` after the last trade;
4. `unknown`: neither (a data gap alone is never evidence of failure, constitution II).
Returns follow `registered.delisting_returns` by class and venue, with 0% and −100% bounds.
Unpriced issuers are not classified: the unpriced-event bounds cover them.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from sentinel.config import registered_value
from sentinel.warehouse import require_tables, table_exists

NYSE_VENUES = {"NYSE", "NYSE MKT", "AMEX", "NYSE ARCA", "NYSE AMERICAN", "NYSE NAT"}
NASDAQ_VENUES = {"NASDAQ"}
BOUNDS = (-1.0, 0.0)
COLUMNS = (
    "issuer_cik VARCHAR, last_session DATE, price_source VARCHAR, ticker VARCHAR, "
    "class VARCHAR, remap_status VARCHAR, evidence_form VARCHAR, evidence_date DATE, "
    "evidence_accession VARCHAR, venue VARCHAR, delisting_return DOUBLE, bound_low DOUBLE, "
    "bound_high DOUBLE"
)


@dataclass
class DelistingReport:
    ended_early: int = 0
    classes: dict[str, int] = field(default_factory=dict)
    venues: dict[str, int] = field(default_factory=dict)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _matches(form: str, forms) -> bool:
    """Prefix match, so amendments (`/A`) and variants count."""
    return any(form.startswith(f) for f in forms)


def venue_of(exchanges) -> str:
    names = {(e or "").upper() for e in exchanges}
    if names & NASDAQ_VENUES:
        return "nasdaq"
    if names & NYSE_VENUES:
        return "nyse"
    return "other"


def delisting_return(params: dict, cls: str, venue: str) -> float:
    returns = registered_value(params, "delisting_returns")
    if cls == "acquired":
        return returns["acquired"]
    if venue == "other":
        venue = {"performance_nasdaq": "nasdaq"}.get(returns["other_venue_treated_as"], "nyse")
    if venue == "nyse":
        return returns["performance_nyse_or_nyse_american"]
    return returns["performance_nasdaq"]


def classify(params: dict, last: date, filings: list[tuple]) -> tuple[str, tuple | None]:
    """(class, deciding filing) for a series whose last trade is `last`; `filings` are
    (form, filing_date, accession) tuples of the issuer."""
    rules = params["rules"]
    later_reports = [
        f
        for f in filings
        if f[0].startswith(("10-Q", "10-K"))
        and f[1] > last + timedelta(days=rules["remap_after_days"])
    ]
    if later_reports:
        return "remap", min(later_reports, key=lambda f: (f[1], f[2]))
    since = add_months(last, -registered_value(params, "merger_lookback"))
    mergers = [
        f for f in filings
        if _matches(f[0], rules["delisting_merger_forms"]) and since <= f[1] <= last
    ]  # fmt: skip
    if mergers:
        return "acquired", max(mergers, key=lambda f: (f[1], f[2]))
    until = add_months(last, rules["delisting_notice_after_months"])
    notices = [
        f for f in filings
        if _matches(f[0], rules["delisting_performance_forms"]) and since <= f[1] <= until
    ]  # fmt: skip
    if notices:
        return "performance", min(notices, key=lambda f: (abs((f[1] - last).days), f[2]))
    return "unknown", None


def _venues(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Venue per issuer: Tiingo issuers by the last exchange-listed ticker in Tiingo's list; Yahoo
    issuers by their current SEC exchanges."""
    out: dict[str, str] = {}
    if table_exists(con, "core.tiingo_listing"):
        for cik, exchange in con.execute(
            """
            select s.issuer_cik, arg_max(l.list_exchange, coalesce(l.list_end, date '9999-12-31'))
            from core.price_series s join core.tiingo_listing l on l.ticker = s.ticker
            where s.price_source = 'tiingo' and l.list_exchange in (
                'NYSE', 'NYSE MKT', 'AMEX', 'NYSE ARCA', 'NYSE NAT', 'NASDAQ')
            group by 1
            """
        ).fetchall():
            out[cik] = venue_of([exchange])
    if table_exists(con, "core.issuer"):
        for cik, exchanges in con.execute(
            "select issuer_cik, exchanges from core.issuer"
        ).fetchall():
            out.setdefault(cik, venue_of(exchanges or []))
    return out


def build(con: duckdb.DuckDBPyConnection, params: dict) -> DelistingReport:
    """Rebuild `core.delisting`."""
    require_tables(con, ["core.price_series", "core.price_daily", "core.session"], "prices")
    require_tables(con, ["core.company_filing"], "company-facts")
    gap = params["rules"]["delisting_end_gap_sessions"]
    ended = con.execute(
        """
        with main as (
            select issuer_cik, price_source, ticker from core.price_series
            where chosen and role <> 'fill_in'
        ),
        last as (
            select d.issuer_cik, max(d.session) as last_session from core.price_daily d group by 1
        )
        select m.issuer_cik, l.last_session, m.price_source, m.ticker
        from main m join last l using (issuer_cik)
        join core.session s on s.session = l.last_session
        where s.session_no < (select max(session_no) from core.session) - ?
        order by 1
        """,
        [gap],
    ).fetchall()
    filings: dict[str, list[tuple]] = {}
    for cik, form, filed, acc in con.execute(
        "select issuer_cik, form, filing_date, accession from core.company_filing "
        "where filing_date is not null"
    ).fetchall():
        filings.setdefault(cik, []).append((form, filed, acc))
    venues = _venues(con)
    rows, report = [], DelistingReport(ended_early=len(ended))
    for cik, last, source, ticker in ended:
        cls, evidence = classify(params, last, filings.get(cik, []))
        venue = venues.get(cik, "other")
        return_cls = "acquired" if cls == "acquired" else "performance"
        rows.append((
            cik, last, source, ticker, cls, "not_found" if cls == "remap" else None,
            evidence[0] if evidence else None, evidence[1] if evidence else None,
            evidence[2] if evidence else None, venue,
            delisting_return(params, return_cls, venue), *BOUNDS,
        ))  # fmt: skip
        report.classes[cls] = report.classes.get(cls, 0) + 1
        report.venues[venue] = report.venues.get(venue, 0) + 1
    con.execute("begin transaction")
    try:
        con.execute(f"create or replace table core.delisting ({COLUMNS})")
        if rows:
            con.executemany(
                "insert into core.delisting values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    return report


def check_delistings(con: duckdb.DuckDBPyConnection, params: dict) -> list[str]:
    """W23: classified issuers really end early, and returns follow class and venue."""
    gap = params["rules"]["delisting_end_gap_sessions"]
    problems = [
        f"{r[0]} does not end early"
        for r in con.execute(
            """
            select d.issuer_cik from core.delisting d
            join core.session s on s.session = d.last_session
            where s.session_no >= (select max(session_no) from core.session) - ?
            """,
            [gap],
        ).fetchall()
    ]
    for cik, cls, venue, ret, low, high in con.execute(
        "select issuer_cik, class, venue, delisting_return, bound_low, bound_high "
        "from core.delisting"
    ).fetchall():
        expected = delisting_return(
            params, "acquired" if cls == "acquired" else "performance", venue
        )
        if ret != expected or (low, high) != BOUNDS:
            problems.append(f"{cik} return {ret} != {expected} for {cls}/{venue}")
    return problems
