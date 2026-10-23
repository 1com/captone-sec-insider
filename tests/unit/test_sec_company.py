"""SEC bulk company data: filing histories and profiles (T039), XBRL facts (T048)."""

from datetime import date

import pytest
from conftest import submissions_zip, universe_tables

from sentinel import warehouse
from sentinel.core import company
from sentinel.warehouse import MissingInput

FILINGS = [  # newest first, as the SEC lists them
    ("a6", "10-Q", "2016-05-01", "2016-03-31", ""),
    ("a5", "4", "2016-04-01", None, ""),
    ("a4", "25-NSE", "2016-03-01", None, ""),
    ("a3", "SC 14D9", "2016-02-01", None, ""),
    ("a2", "4/A", "2016-01-15", None, ""),
    ("a1", "425", "2016-01-10", None, ""),
    ("a0", "8-K", "2016-01-02", None, "2.01,9.01"),
]


@pytest.fixture
def con(tmp_data):
    con = warehouse.connect(tmp_data)
    universe_tables(con)
    con.executemany(
        "insert into evt.prelim_event values (?, ?)",
        [("100", date(2015, 1, 5)), ("200", date(2012, 3, 1)), ("300", date(2010, 5, 1))],
    )
    yield con
    con.close()


def write_submissions(paths, companies, recent_size=1000):
    paths.sec_company.mkdir(parents=True, exist_ok=True)
    (paths.sec_company / "submissions.zip").write_bytes(submissions_zip(companies, recent_size))


COMPANIES = {
    "100": {"name": "Abc Corp", "sic": "3674", "sic_label": "Semiconductors",
            "exchanges": ["Nasdaq"], "tickers": ["ABC"], "filings": FILINGS},
    "200": {"name": "Gone Inc", "sic": "", "exchanges": [], "tickers": [], "filings": []},
    "300": {"name": "Early Co", "sic": "1000", "filings": [("b1", "10-K", "2010-03-01", None, "")]},
}  # fmt: skip


def test_filing_history_merges_pages_and_drops_insider_forms(con, tmp_data, params):
    write_submissions(tmp_data, COMPANIES, recent_size=3)  # a6–a4 recent, a3–a0 on a page
    n_issuers, n_filings = company.build_profiles(con, tmp_data, params)
    assert n_issuers == 2  # 300's only event is before the final detection start
    rows = con.execute(
        "select accession, form, filing_date, report_date, items from core.company_filing "
        "where issuer_cik = '100' order by filing_date"
    ).fetchall()
    assert [r[1] for r in rows] == ["8-K", "425", "SC 14D9", "25-NSE", "10-Q"]
    assert rows[0][4] == "2.01,9.01" and rows[-1][3] == date(2016, 3, 31)
    assert n_filings == 5


def test_profiles_hold_current_sic_and_exchanges(con, tmp_data, params):
    write_submissions(tmp_data, COMPANIES)
    company.build_profiles(con, tmp_data, params)
    rows = con.execute(
        "select issuer_cik, name, sic, sic_label, exchanges, tickers from core.issuer order by 1"
    ).fetchall()
    assert rows == [
        ("100", "Abc Corp", "3674", "Semiconductors", ["Nasdaq"], ["ABC"]),
        ("200", "Gone Inc", None, None, [], []),
    ]


def test_missing_archive_is_reported(con, tmp_data, params):
    with pytest.raises(MissingInput, match="fetch-company"):
        company.build_profiles(con, tmp_data, params)
