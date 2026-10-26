"""Tiingo: paid-window guard, ticker resolution, identity check, storage (T011). Synthetic data."""

import gzip
import io
import json
import zipfile
from datetime import date

import duckdb
import httpx
import pytest
import respx
from conftest import tiingo_csv

from sentinel.core.tiingo_register import OutsidePaidWindow, require_paid_window
from sentinel.ingest import manifest, tiingo
from sentinel.ingest.http import RateLimiter, RetryPolicy

BASE = "https://api.tiingo.com/tiingo/daily"
INSIDE = date(2026, 11, 2)
TEST_FROM = date(2026, 10, 29)  # the tests' own paid window, not the one in params.yaml


@pytest.fixture
def paid(params):
    params["ops"]["tiingo_paid_from"] = TEST_FROM
    params["ops"]["tiingo_paid_until"] = date(2026, 11, 28)
    return params


@pytest.mark.parametrize(
    ("until", "today"),
    [(None, date(2026, 11, 2)), (date(2026, 11, 28), date(2026, 10, 28)),
     (date(2026, 11, 28), date(2026, 11, 28))],
)  # fmt: skip
def test_writes_are_refused_outside_the_paid_window(params, until, today):
    params["ops"]["tiingo_paid_from"] = TEST_FROM
    params["ops"]["tiingo_paid_until"] = until
    with pytest.raises(OutsidePaidWindow):
        require_paid_window(params, today)


def test_writes_are_allowed_inside_the_paid_window(paid):
    require_paid_window(paid, INSIDE)


def test_client_sends_the_token_in_a_header_not_the_url():
    client = tiingo.make_client("tiingo-secret-123", 30)
    assert client.headers["Authorization"] == "Token tiingo-secret-123"
    assert "@" not in client.headers["User-Agent"]  # never the SEC contact


def _listing_zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        lines = ["ticker,exchange,assetType,priceCurrency,startDate,endDate"]
        lines += [",".join(r) for r in rows]
        zf.writestr("supported_tickers.csv", "\n".join(lines) + "\n")
    return buf.getvalue()


def test_listing_keeps_the_exchange_of_each_interval(params):
    payload = _listing_zip([("XYZ", "NASDAQ", "Stock", "USD", "2005-01-03", "2012-05-01"),
                            ("XYZQ", "PINK", "Stock", "USD", "2012-05-02", "2013-01-15"),
                            ("FUND", "NYSE", "Mutual Fund", "USD", "2005-01-03", "")])  # fmt: skip
    listing = tiingo.parse_listing(payload, params["provisional"]["tiingo_us_exchanges"])
    assert listing["XYZ"] == [(date(2005, 1, 3), date(2012, 5, 1), "NASDAQ")]
    assert listing["XYZQ"] == [(date(2012, 5, 2), date(2013, 1, 15), "PINK")]
    assert "FUND" not in listing


@pytest.fixture
def con():
    con = duckdb.connect()
    for schema in ("core", "evt"):
        con.execute(f"create schema {schema}")
    con.execute(
        "create table core.symbol_map (issuer_cik VARCHAR, ticker VARCHAR, valid_from DATE, "
        "valid_to DATE, price_source VARCHAR, match_quality VARCHAR)"
    )
    con.execute("create table evt.prelim_event (issuer_cik VARCHAR, signal_date DATE)")
    con.execute(
        "create table core.filing (accession VARCHAR, issuer_cik VARCHAR, filing_date DATE, "
        "symbol_raw VARCHAR, issuer_name VARCHAR)"
    )
    return con


def _issuer(con, cik, tickers, filings, source="tiingo", event="2012-03-01"):
    for t in tickers:
        con.execute(
            "insert into core.symbol_map values (?, ?, '2008-01-01', '2012-04-01', ?, 'x')",
            [cik, t, source],
        )
    con.execute("insert into evt.prelim_event values (?, ?)", [cik, event])
    for i, (d, symbol, name) in enumerate(filings):
        con.execute(
            "insert into core.filing values (?, ?, ?, ?, ?)", [f"{cik}-{i}", cik, d, symbol, name]
        )


LISTING = {
    "XYZ": [(date(1999, 1, 4), date(2003, 6, 1), "NYSE")],  # an older company, same ticker
    "XYZQ": [(date(2009, 1, 2), date(2013, 1, 15), "PINK")],
    "ABC": [(date(2005, 1, 3), date(2011, 2, 1), "NASDAQ")],
    "ABCD": [(date(2011, 2, 2), date(2014, 9, 30), "NASDAQ")],
}


def test_q_suffix_resolves_when_only_it_overlaps_the_filings(con, params):
    _issuer(con, "10", ["XYZ"], [("2009-03-01", "XYZ", "Xyz Corp"), ("2012-04-01", "XYZ", "Xyz")])
    [target] = tiingo.resolve(con, LISTING, params)
    assert (target.issuer_cik, target.ticker, target.role) == ("10", "XYZQ", "primary")
    assert target.exchange == "PINK" and target.base_ticker == "XYZ"


def test_the_match_ending_last_is_primary_and_the_others_fill_in(con, params):
    _issuer(con, "20", ["ABC", "ABCD"],
            [("2008-01-02", "ABC", "Abc Inc"), ("2014-08-01", "ABCD", "Abc Inc")])  # fmt: skip
    targets = {t.ticker: t.role for t in tiingo.resolve(con, LISTING, params)}
    assert targets == {"ABCD": "primary", "ABC": "fill_in"}


def test_yahoo_fallback_issuers_get_the_fallback_role(con, params):
    _issuer(con, "30", ["ABCD"], [("2012-01-02", "ABCD", "Abc Inc")], source="yahoo")
    [target] = tiingo.resolve(con, LISTING, params, fallback_issuers=["30"])
    assert (target.ticker, target.role) == ("ABCD", "fallback")


def test_issuers_without_a_match_are_left_out(con, params):
    _issuer(con, "40", ["NOPE"], [("2012-01-02", "NOPE", "Nope Inc")])
    assert tiingo.resolve(con, LISTING, params) == []


def _meta(name, start="2009-01-02", end=None):
    return {"name": name, "startDate": start, "endDate": end}


@pytest.mark.parametrize(
    ("meta", "names", "expected"),
    [
        (_meta("XYZ Corp", end="2013-01-15"), ["Xyz Corp"], "ok"),
        (_meta("Xyz Holdings Inc"), ["XYZ CORP"], "ok"),
        (_meta("Other Corp", "2016-01-04", "2020-01-15"), ["Xyz"], "dates"),
        (_meta("Other Group Inc"), ["Xyz Inc"], "name"),
        (_meta("Xyz", start=None), ["Xyz"], "no_data"),
        (None, ["Xyz"], "no_data"),
        (_meta("New Name Inc"), ["Old Name Inc", "Xyz"], "ok"),  # any SEC name of the issuer
    ],
)
def test_identity_check(meta, names, expected):
    assert tiingo.identity(meta, names, (date(2009, 3, 1), date(2012, 4, 1))) == expected


def _net():
    return {
        "limiter": RateLimiter(2, 2, clock=lambda: 0.0, sleep=lambda s: None),
        "policy": RetryPolicy(2, 0.0, 0.0, sleep=lambda s: None),
    }


def _targets():
    return [
        tiingo.Target("10", "XYZQ", "primary", "XYZ", date(2009, 3, 1), date(2012, 4, 1), "PINK",
                      date(2013, 1, 15)),
        tiingo.Target("50", "GONE", "primary", "GONE", date(2009, 3, 1), date(2012, 4, 1), "NYSE",
                      date(2012, 6, 1)),
    ]  # fmt: skip


@respx.mock
def test_meta_and_prices_are_stored_gzipped_with_manifest_lines(tmp_data, paid):
    meta = {"ticker": "xyzq", "name": "Xyz Corp", "exchangeCode": "PINK",
            "startDate": "2009-01-02", "endDate": "2013-01-15", "description": ""}  # fmt: skip
    csv_text = tiingo_csv([{"session": date(2012, 1, 3), "close": 1.5}])
    m1 = respx.get(f"{BASE}/XYZQ").mock(return_value=httpx.Response(200, json=meta))
    p1 = respx.get(f"{BASE}/XYZQ/prices").mock(return_value=httpx.Response(200, text=csv_text))
    m2 = respx.get(f"{BASE}/GONE").mock(return_value=httpx.Response(404, json={"detail": "x"}))
    p2 = respx.get(f"{BASE}/GONE/prices")
    client = tiingo.make_client("tiingo-secret-123", 30)
    report = tiingo.fetch(tmp_data, paid, client, targets=_targets(), today=INSIDE, **_net())
    assert (report.stored, report.not_found) == (1, ["GONE"])
    assert p1.calls.last.request.url.params["startDate"] == "2010-01-01"
    assert p1.calls.last.request.url.params["format"] == "csv"
    assert not p2.called
    prices = tmp_data.tiingo / "prices" / "XYZQ.csv.gz"
    assert gzip.decompress(prices.read_bytes()).decode() == csv_text
    assert (
        json.loads(gzip.decompress((tmp_data.tiingo / "meta" / "XYZQ.json.gz").read_bytes()))[
            "name"
        ]
        == "Xyz Corp"
    )
    entries = [e for e in manifest.read_all(tmp_data.manifest) if e.source == "tiingo"]
    assert {e.key for e in entries} == {"meta/XYZQ", "prices/XYZQ", "meta/GONE"}
    assert all("secret" not in e.url and "token" not in e.url.lower() for e in entries)
    # A rerun fetches nothing
    calls = m1.call_count + m2.call_count
    tiingo.fetch(tmp_data, paid, client, targets=_targets(), today=INSIDE, **_net())
    assert m1.call_count + m2.call_count == calls


@respx.mock
def test_fetch_refuses_outside_the_window_before_any_request(tmp_data, params):
    params["ops"]["tiingo_paid_until"] = None
    route = respx.get(f"{BASE}/XYZQ")
    client = tiingo.make_client("k" * 8, 30)
    with pytest.raises(OutsidePaidWindow):
        tiingo.fetch(tmp_data, params, client, targets=_targets(), today=INSIDE, **_net())
    assert not route.called and not tmp_data.tiingo.exists()


def test_store_list_writes_the_zip_with_a_manifest_line(tmp_data, paid):
    payload = _listing_zip([("XYZ", "NASDAQ", "Stock", "USD", "2005-01-03", "2012-05-01")])
    tiingo.store_list(tmp_data, paid, payload, "https://example/supported_tickers.zip", INSIDE)
    entry = manifest.find_original(tmp_data.manifest, "tiingo", "supported_tickers")
    assert entry.path == "tiingo/supported_tickers.zip"
    assert tiingo.stored_listing(tmp_data, paid)["XYZ"][0][2] == "NASDAQ"
    with pytest.raises(OutsidePaidWindow):
        tiingo.store_list(tmp_data, paid, payload, "u", date(2026, 12, 1))
