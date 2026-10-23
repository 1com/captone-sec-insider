"""Step 6: issuer → price-symbol map from SEC data only (FR-017 – FR-019; W10, W11)."""

import csv
import io
import json
import zipfile
from datetime import date

import pytest
from conftest import line, owner, sub

from sentinel.core import symbols

SNAPSHOT = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [100, "LISTED CORP", "ABC", "Nasdaq"],
        [200, "OTC CORP", "OTCX", "OTC"],
        [250, "NOX CORP", "NOX", None],
    ],
}


def filing(acc, date_str, cik, symbol, name, buy=False):
    """A filing by a director of `cik`; with `buy`, a $150,000 purchase (a B2 event)."""
    lines = [line(acc, "1", tdate=date_str, shares="3000", price="50")] if buy else []
    return [sub(acc, date=date_str, cik=cik, symbol=symbol, name=name)], [owner(acc)], lines


FILINGS = [
    filing("l1", "01-MAR-2018", "100", "ABC", "Listed Corp", buy=True),
    filing("o1", "01-MAR-2019", "200", "OTCX", "Otc Corp"),
    filing("n1", "01-APR-2019", "250", "NOX", "Nox Corp"),
    filing("d1", "03-MAR-2014", "300", "ABC", "Gone Inc"),
    filing("d2", "01-JUN-2016", "300", "abc", "Gone Inc"),
    filing("d3", "01-FEB-2017", "300", "ABCD", "Gone Inc"),
    filing("d4", "01-MAY-2019", "300", "ABCD", "Gone Inc", buy=True),
    filing("u1", "01-MAR-2019", "400", "NONE", "Blank Co"),
    filing("u2", "01-MAR-2019", "500", "", "Acme Income Fund"),
    filing("x1", "02-JUL-2019", "600", "XA, XB", "Dual Class Co", buy=True),
]


@pytest.fixture
def built(archives, pipeline, tmp_path):
    snapshot = tmp_path / "company_tickers_exchange_20261022.json"
    snapshot.write_text(json.dumps(SNAPSHOT))
    tables = {"SUBMISSION": [], "REPORTINGOWNER": [], "NONDERIV_TRANS": []}
    for subs, owners, lines in FILINGS:
        tables["SUBMISSION"] += subs
        tables["REPORTINGOWNER"] += owners
        tables["NONDERIV_TRANS"] += lines
    archives({"2019q3": tables})
    return pipeline(until="symbols", snapshot=snapshot), snapshot


def test_the_map_has_current_and_historic_tickers(built):
    con, _ = built
    rows = con.execute(
        "select issuer_cik, ticker, valid_from, valid_to, price_source, match_quality "
        "from core.symbol_map order by all"
    ).fetchall()
    assert rows == [
        ("100", "ABC", date(2018, 3, 1), None, "yahoo", "sec_current"),
        ("200", "OTCX", date(2019, 3, 1), None, "yahoo", "sec_current_otc"),
        ("250", "NOX", date(2019, 4, 1), None, "yahoo", "sec_current_otc"),
        ("300", "ABC", date(2014, 3, 3), date(2016, 6, 1), "tiingo", "form4_history"),
        ("300", "ABCD", date(2017, 2, 1), date(2019, 5, 1), "tiingo", "form4_history"),
        ("600", "XA", date(2019, 7, 2), date(2019, 7, 2), "tiingo", "form4_history"),
        ("600", "XB", date(2019, 7, 2), date(2019, 7, 2), "tiingo", "form4_history"),
    ]


def test_companies_without_a_ticker_are_listed_with_a_reason(built):
    con, _ = built
    assert con.execute(
        "select issuer_cik, issuer_name, reason from core.symbol_unmatched order by all"
    ).fetchall() == [("400", "Blank Co", "no_ticker"), ("500", "Acme Income Fund", "fund_like")]


def test_every_event_company_is_mapped_or_listed(built):
    con, snapshot = built
    assert symbols.check_events_covered(con) == []  # W10
    assert symbols.check_sec_only(con, snapshot) == []  # W11
    con.execute("delete from core.symbol_map where issuer_cik = '300'")
    assert symbols.check_events_covered(con) == ["300"]


def test_coverage_counts_event_companies(built):
    con, _ = built
    assert symbols.coverage(con) == {
        "event_companies": 3,
        "mapped": 3,
        "yahoo": 1,
        "tiingo": 2,
        "unmatched": {},
    }


def tiingo_zip(rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["ticker", "exchange", "assetType", "priceCurrency", "startDate", "endDate"])
    writer.writerows(rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("supported_tickers.csv", out.getvalue())
    return buf.getvalue()


def test_tiingo_report_counts_in_memory_and_stores_nothing(built, params, monkeypatch, tmp_path):
    con, snapshot = built
    listing = tiingo_zip(
        [
            ["ABCD", "PINK", "Stock", "USD", "2015-01-01", "2020-01-01"],
            ["XBQ", "OTCMKTS", "Stock", "USD", "2010-01-01", "2021-01-01"],
            ["ZZZ", "NYSE", "Stock", "USD", "2010-01-01", ""],
        ]
    )
    monkeypatch.setattr(symbols, "fetch_list", lambda url, timeout: (listing, None, "sha"))
    before = sorted(p.name for p in tmp_path.rglob("*"))
    report = symbols.tiingo_coverage(con, params)
    assert report == {"companies": 2, "matched": 2, "q_suffix": 1, "ticker_only": 0, "unmatched": 0}
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
    assert symbols.check_sec_only(con, snapshot) == []
    assert "ZZZ" not in {r[0] for r in con.execute("select ticker from core.symbol_map").fetchall()}
