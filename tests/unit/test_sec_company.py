"""SEC bulk company data: filing histories and profiles (T039), XBRL facts (T048)."""

import io
import json
import zipfile
from datetime import date

import pytest
from conftest import companyfacts_zip, submissions_zip, universe_tables

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


# --- XBRL facts (T048; spec US4 acceptance 1 and 3) ---------------------------------------------


def fact(end, val, filed, accn, start=None, form="10-Q", fp="Q1"):
    f = {"end": end, "val": val, "filed": filed, "accn": accn, "form": form, "fp": fp}
    return f | ({"start": start} if start else {})


def facts_of(doc_tags, cik="100", cutoff=None):
    with zipfile.ZipFile(io.BytesIO(companyfacts_zip({cik: doc_tags}))) as zf:
        doc = json.loads(zf.read(f"CIK{int(cik):010d}.json"))
    return {(r[1], r[3], r[4]): r for r in company.first_filed(doc, cik, cutoff)}


def test_restated_values_keep_the_first_filing():
    rows = facts_of({"us-gaap:Assets": {"USD": [
        fact("2018-12-31", 900, "2019-03-01", "0001-19-000002"),
        fact("2018-12-31", 950, "2020-03-01", "0001-20-000001", form="10-K/A"),  # restated
        fact("2018-12-31", 910, "2019-03-01", "0001-19-000001"),  # same day: smaller accession
    ]}})  # fmt: skip
    r = rows[("assets", None, date(2018, 12, 31))]
    assert (r[5], r[6], r[7], r[10]) == (910.0, date(2019, 3, 1), "0001-19-000001", "main:Assets")


def test_fallback_tags_fill_only_periods_the_main_tag_lacks():
    rows = facts_of({
        "us-gaap:StockholdersEquity": {"USD": [fact("2019-03-31", 100, "2019-05-01", "a")]},
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": {
            "USD": [fact("2019-03-31", 120, "2019-05-01", "a"),
                    fact("2019-06-30", 130, "2019-08-01", "b")]},
        "us-gaap:ProfitLoss": {"USD": [fact("2019-06-30", -5, "2019-08-01", "b",
                                            start="2019-04-01")]},
    })  # fmt: skip
    q1, q2 = rows[("equity", None, date(2019, 3, 31))], rows[("equity", None, date(2019, 6, 30))]
    assert (q1[5], q1[10]) == (100.0, "main:StockholdersEquity")
    assert q2[5] == 130.0 and q2[10].startswith("fallback:")
    ni = rows[("net_income", date(2019, 4, 1), date(2019, 6, 30))]
    assert (ni[5], ni[10]) == (-5.0, "fallback:ProfitLoss")


def test_shares_come_only_from_the_cover_page_tag():
    cover = {"shares": [fact("2019-04-30", 5e6, "2019-05-01", "a")]}
    balance = {"shares": [fact("2019-03-31", 4e6, "2019-05-01", "a")]}
    rows = facts_of({"dei:EntityCommonStockSharesOutstanding": cover,
                     "us-gaap:CommonStockSharesOutstanding": balance})  # fmt: skip
    assert [(k, r[2], r[5]) for k, r in rows.items()] == [
        (("shares_outstanding", None, date(2019, 4, 30)), "shares", 5e6)
    ]


def test_cutoff_drops_facts_filed_after_it():
    tags = {"us-gaap:Assets": {"USD": [fact("2018-12-31", 900, "2019-03-01", "a"),
                                       fact("2019-03-31", 950, "2019-05-01", "b")]}}  # fmt: skip
    assert len(facts_of(tags, cutoff=date(2019, 4, 1))) == 1


def test_build_facts_loads_the_universe(con, tmp_data, params):
    tmp_data.sec_company.mkdir(parents=True, exist_ok=True)
    tags = {"us-gaap:Assets": {"USD": [fact("2018-12-31", 900, "2019-03-01", "a")]}}
    (tmp_data.sec_company / "companyfacts.zip").write_bytes(
        companyfacts_zip({"100": tags, "300": tags})
    )
    report = company.build_facts(con, tmp_data, params)
    assert (report.issuers, report.with_facts, report.rows) == (2, 1, 1)
    assert company.check_first_filed(con) == []
