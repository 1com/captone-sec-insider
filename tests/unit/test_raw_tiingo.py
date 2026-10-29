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
