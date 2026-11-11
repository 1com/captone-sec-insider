"""Tiingo downloads: new days for Tiingo-priced listed companies, only inside the paid plan, the
token never in a URL (respx; no network)."""

from datetime import date

import httpx
import pytest
import respx

from sentinel import db
from sentinel.raw import tiingo
from sentinel.raw.manifest import Manifest

QUIET = {"echo": lambda s: None}
CSV = ("date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,divCash,"
       "splitFactor\n2026-10-28,5,5,5,5,10,5,5,5,5,10,0.0,1.0\n")  # fmt: skip


@pytest.fixture
def priced(tmp_data, fake_env):
    con = db.connect(tmp_data)
    con.execute("create table ref.security (ticker VARCHAR, source VARCHAR, listed BOOLEAN)")
    con.execute("insert into ref.security values ('GWI', 'tiingo', true), "
                "('AAPL', 'yahoo', true), ('GONE', 'tiingo', false)")  # fmt: skip
    con.execute("create table stg_tiingo.price (ticker VARCHAR, session DATE)")
    con.execute("insert into stg_tiingo.price values ('GWI', '2026-10-27'), ('GONE', '2015-06-30')")
    yield tmp_data, con
    con.close()


@respx.mock
def test_new_days_are_asked_from_the_day_after_the_last_and_the_token_stays_in_a_header(priced):
    p, con = priced
    route = respx.get("https://api.tiingo.com/tiingo/daily/GWI/prices").mock(
        return_value=httpx.Response(200, text=CSV)
    )
    report = tiingo.fetch_new_days(p, date(2026, 10, 30), con=con, **QUIET)
    assert route.call_count == 1  # listed Tiingo companies only: not AAPL (Yahoo), not GONE
    request = route.calls[0].request
    assert request.url.params["startDate"] == "2026-10-28"
    assert request.headers["Authorization"] == "Token tiingo-secret-123"
    entry = Manifest(p.manifest).find_original("tiingo", "daily/2026-10-30/GWI")
    assert "tiingo-secret-123" not in entry.url
    assert entry.path == "tiingo/daily/2026-10-30/GWI.csv.gz"
    assert report.latest_date == date(2026, 10, 28)
    assert tiingo.fetch_new_days(p, date(2026, 10, 30), con=con, **QUIET).requests == 0


@respx.mock(assert_all_called=False)
def test_nothing_is_asked_outside_the_paid_plan(priced):
    p, con = priced
    route = respx.get("https://api.tiingo.com/tiingo/daily/GWI/prices")
    report = tiingo.fetch_new_days(p, date(2026, 11, 26), con=con, **QUIET)
    assert (report.status, report.requests, route.call_count) == ("skipped: plan ended", 0, 0)


@respx.mock
def test_a_dividend_in_the_new_days_brings_the_full_series_again(priced):
    p, con = priced
    with_dividend = CSV.replace("0.0,1.0\n", "0.42,1.0\n")
    route = respx.get("https://api.tiingo.com/tiingo/daily/GWI/prices").mock(
        side_effect=[httpx.Response(200, text=with_dividend), httpx.Response(200, text=CSV)]
    )
    report = tiingo.fetch_new_days(p, date(2026, 10, 30), con=con, **QUIET)
    assert route.call_count == 2 and report.files_stored == 2
    assert route.calls[1].request.url.params["startDate"] == "2010-01-01"
    assert Manifest(p.manifest).find_original("tiingo", "history/GWI/2026-10-30") is not None


@pytest.fixture
def former(tmp_data, fake_env):
    """MGP-like: OLD in the company's own Form 4s, not stored, in Tiingo's list; NEWT stored;
    PRE's only Tiingo line ended before 2010; FAR's line does not overlap the company's use."""
    con = db.connect(tmp_data)
    con.execute("create table ref.ticker_history (cik VARCHAR, ticker VARCHAR, exchange VARCHAR, "
                "valid_from DATE, valid_to DATE, evidence VARCHAR)")  # fmt: skip
    con.execute("insert into ref.ticker_history values "
                "('1', 'OLD', null, '2010-02-01', '2026-10-23', 'form4'), "
                "('1', 'NEWT', null, '2026-11-05', null, 'sec_list'), "
                "('2', 'PRE', null, '2008-01-02', '2009-06-01', 'form4'), "
                "('3', 'FAR', null, '2011-01-03', '2012-01-03', 'form4')")  # fmt: skip
    con.execute("create table stg_tiingo.listing (ticker VARCHAR, exchange VARCHAR, "
                "asset_type VARCHAR, currency VARCHAR, start_date DATE, "
                "end_date DATE)")  # fmt: skip
    con.execute("insert into stg_tiingo.listing values "
                "('OLD', 'NASDAQ', 'Stock', 'USD', '1990-03-26', '2026-10-23'), "
                "('PRE', 'NYSE', 'Stock', 'USD', '2001-01-02', '2009-06-30'), "
                "('FAR', 'NYSE', 'Stock', 'USD', '2019-01-02', null)")  # fmt: skip
    con.execute("create table stg_tiingo.price (ticker VARCHAR, session DATE)")
    con.execute("create table stg_yahoo.price (ticker VARCHAR, session DATE)")
    con.execute("insert into stg_yahoo.price values ('NEWT', '2026-11-05')")
    yield tmp_data, con
    con.close()


@respx.mock
def test_old_tickers_are_asked_once_with_their_description(former):
    p, con = former
    meta = respx.get("https://api.tiingo.com/tiingo/daily/OLD").mock(
        return_value=httpx.Response(200, json={"ticker": "OLD", "name": "Old Name Inc"})
    )
    series = respx.get("https://api.tiingo.com/tiingo/daily/OLD/prices").mock(
        return_value=httpx.Response(200, text=CSV)
    )
    assert tiingo.former_targets(con) == ["OLD"]  # not NEWT (stored), PRE (before 2010), FAR
    report = tiingo.fetch_former(p, date(2026, 11, 12), con=con, **QUIET)
    assert (meta.call_count, series.call_count, report.files_stored) == (1, 1, 2)
    assert series.calls[0].request.url.params["startDate"] == "2010-01-01"
    assert series.calls[0].request.headers["Authorization"] == "Token tiingo-secret-123"
    book = Manifest(p.manifest)
    assert book.find_original("tiingo", "former/OLD").path == "tiingo/former/OLD.csv.gz"
    assert book.find_original("tiingo", "former_meta/OLD").path == "tiingo/former_meta/OLD.json.gz"
    assert "tiingo-secret-123" not in book.find_original("tiingo", "former/OLD").url
    assert tiingo.fetch_former(p, date(2026, 11, 12), con=con, **QUIET).requests == 0


@respx.mock(assert_all_called=False)
def test_old_tickers_are_not_asked_after_the_paid_plan(former):
    p, con = former
    route = respx.get("https://api.tiingo.com/tiingo/daily/OLD/prices")
    report = tiingo.fetch_former(p, date(2026, 11, 26), con=con, **QUIET)
    assert (report.status, report.requests, route.call_count) == ("skipped: plan ended", 0, 0)
