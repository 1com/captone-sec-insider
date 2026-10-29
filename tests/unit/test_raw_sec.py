"""SEC downloads: the shared rate limit, filing days, the daily index and per-filing documents
(respx answers every request; the index excerpt and headers are real SEC files)."""

import re
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from sentinel import db
from sentinel.config import sources
from sentinel.raw import sec
from sentinel.raw.http import RateLimiter
from sentinel.raw.manifest import Manifest, read_stored

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sec"
S3_MISSING = "<Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>"
COMPANIES = ["1001385", "1005284", "1015739", "1018979", "1021635", "1021860", "1023128",
             "1025378", "1031296"]  # fmt: skip
QUIET = {"echo": lambda s: None}


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(sec, "_LIMITER", None)


def test_every_sec_source_in_a_process_shares_one_limiter_below_the_sec_ceiling(tmp_data):
    settings = sources(tmp_data)
    one, two = sec.shared_limiter(settings), sec.shared_limiter(settings)
    assert one is two  # sec-daily and form4 run in parallel threads: one rate for both
    assert settings["sec"]["document_requests_per_second"] <= 10


def test_filing_days_skip_weekends_and_the_index_url_names_the_quarter(tmp_data):
    days = sec.filing_days(date(2026, 10, 23), date(2026, 10, 27))
    assert days == [date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 27)]
    assert sec.index_url(sources(tmp_data), date(2026, 10, 28)) == (
        "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/master.20261028.idx"
    )


@pytest.fixture
def sec_env(tmp_data, fake_env, monkeypatch):
    """Known filers: nine companies and one person; a limiter that does not sleep."""
    monkeypatch.setattr(sec, "_LIMITER", RateLimiter(10, 10, sleep=lambda s: None))
    con = db.connect(tmp_data)
    con.execute("create table stg_sec_filings.filer (cik VARCHAR, is_company BOOLEAN)")
    con.executemany("insert into stg_sec_filings.filer values (?, ?)",
                    [(c, True) for c in COMPANIES] + [("1008079", False)])  # fmt: skip
    yield tmp_data, con
    con.close()


def _routes(no_facts: str = "1023128"):
    index = (FIXTURES / "master.20261028.idx").read_text()
    respx.get(re.compile(r".*/master\.20261028\.idx$")).mock(
        return_value=httpx.Response(200, text=index)
    )
    respx.get(re.compile(r".*/master\.\d{8}\.idx$")).mock(
        return_value=httpx.Response(403, text=S3_MISSING)
    )  # not published yet
    headers = respx.get(re.compile(r".*-index-headers\.html$")).mock(
        return_value=httpx.Response(200, text=(FIXTURES / "header_8k.html").read_text())
    )
    facts = respx.get(re.compile(r".*/companyfacts/CIK\d{10}\.json$")).mock(
        side_effect=lambda req: httpx.Response(404) if no_facts in str(req.url)
        else httpx.Response(200, json={"cik": 1, "facts": {}}))  # fmt: skip
    subs = respx.get(re.compile(r".*/submissions/CIK\d{10}\.json$")).mock(
        return_value=httpx.Response(200, json={"cik": "1019849", "name": "PENSKE"})
    )
    return headers, facts, subs


@respx.mock
def test_a_filing_day_brings_its_index_the_details_used_and_the_new_registrants(sec_env):
    p, con = sec_env
    headers, facts, subs = _routes()
    report = sec.fetch_daily(p, date(2026, 10, 30), con=con, from_day=date(2026, 10, 28),
                             **QUIET)  # fmt: skip
    # 8 8-Ks (one from a CIK first seen today) and 6 10-Qs of companies; Form 3 and 4 filings are
    # left to `form4`
    assert headers.call_count == 14
    assert facts.call_count == 6 and subs.call_count == 1  # the 10-Q filers; the new registrant
    book = Manifest(p.manifest)
    counts = {
        s: len(book.originals(s))
        for s in ("sec_index", "sec_filing_header", "sec_companyfacts_cik", "sec_submissions_cik")
    }
    assert counts == {
        "sec_index": 1,
        "sec_filing_header": 14,
        "sec_companyfacts_cik": 5,
        "sec_submissions_cik": 1,
    }  # one company has no financial values (404)
    assert report.files_stored == 21 and report.latest_date == date(2026, 10, 28)
    assert (p.sec_index / "done-sec-daily.txt").read_text().strip() == "2026-10-28"
    # the next run asks only for the 29th's index, which is not published yet
    again = sec.fetch_daily(p, date(2026, 10, 30), con=con, **QUIET)
    assert (again.requests, again.files_stored, again.status) == (1, 0, "nothing_new")


@respx.mock
def test_an_index_missing_for_days_is_a_holiday_and_is_not_asked_again(sec_env):
    p, con = sec_env
    _routes()
    days = {"from_day": date(2026, 11, 2), "to_day": date(2026, 11, 3)}
    sec.fetch_daily(p, date(2026, 11, 20), con=con, **days, **QUIET)
    assert (p.sec_index / "absent.csv").read_text().split() == ["day", "2026-11-02", "2026-11-03"]
    assert sec.fetch_daily(p, date(2026, 11, 20), con=con, **days, **QUIET).requests == 0


@respx.mock
def test_the_ticker_list_is_stored_once_a_day_and_checked_for_its_layout(sec_env):
    p, _ = sec_env
    good = {"fields": ["cik", "name", "ticker", "exchange"],
            "data": [[320193, "Apple", "AAPL", "Nasdaq"]]}  # fmt: skip
    route = respx.get("https://www.sec.gov/files/company_tickers_exchange.json").mock(
        return_value=httpx.Response(200, json=good)
    )
    assert sec.fetch_tickers(p, date(2026, 10, 30), **QUIET).files_stored == 1
    assert sec.fetch_tickers(p, date(2026, 10, 30), **QUIET).files_stored == 0
    assert route.call_count == 1
    route.mock(return_value=httpx.Response(200, json={"fields": ["x"], "data": []}))
    with pytest.raises(ValueError, match="layout"):
        sec.fetch_tickers(p, date(2026, 10, 31), **QUIET)


@respx.mock
def test_a_new_bulk_copy_goes_to_a_dated_folder_and_never_replaces_the_old_one(sec_env):
    p, _ = sec_env
    urls = {
        "submissions": "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
        "companyfacts": "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
    }
    for name, url in urls.items():
        respx.get(url).mock(return_value=httpx.Response(200, content=b"PK" + name.encode()))
    report = sec.fetch_bulk(p, date(2026, 10, 30), **QUIET)
    assert report.files_stored == 2
    assert (p.sec_company / "2026-10-30" / "companyfacts.zip").read_bytes() == b"PKcompanyfacts"
    keys = sorted(e.key for e in Manifest(p.manifest).originals("sec_company"))
    assert keys == ["companyfacts/2026-10-30", "submissions/2026-10-30"]
    assert sec.fetch_bulk(p, date(2026, 10, 30), **QUIET).files_stored == 0


INSIDER = {
    "0001437749-26-033807": "form4_purchase.txt",
    "0001204816-26-000057": "form4_checkbox.txt",
    "0001040470-26-000320": "form3.txt",
    "0001493152-26-048811": "form4a.txt",
}


def _submissions():
    """Every full submission: the four fixtures as served, a stand-in for the others."""

    def answer(req):
        acc = str(req.url).rsplit("/", 1)[1].removesuffix(".txt")
        name = INSIDER.get(acc)
        return httpx.Response(200, content=(FIXTURES / name).read_bytes() if name
                              else f"<SEC-DOCUMENT>{acc}".encode())  # fmt: skip

    return respx.get(re.compile(r".*/edgar/data/\d+/[\d-]+\.txt$")).mock(side_effect=answer)


@respx.mock
def test_form4_stores_every_insider_filing_of_a_day_once_as_served(sec_env):
    p, _ = sec_env
    _routes()
    route = _submissions()
    report = sec.fetch_ownership(p, date(2026, 10, 30), from_day=date(2026, 10, 28), **QUIET)
    assert route.call_count == 13  # the 3, 4, 4/A filings of the index excerpt
    assert (report.files_stored, report.latest_date) == (14, date(2026, 10, 28))  # with the index
    book = Manifest(p.manifest)
    entry = book.find_original("sec_ownership_filing", "0001437749-26-033807")
    assert entry.path == "sec/form4/2026/0001437749-26-033807.txt.gz"
    assert read_stored(p, entry) == (FIXTURES / "form4_purchase.txt").read_bytes()
    assert (p.sec_index / "done-form4.txt").read_text().strip() == "2026-10-28"
    again = sec.fetch_ownership(p, date(2026, 10, 30), **QUIET)  # only the 29th's index: missing
    assert (again.requests, again.files_stored) == (1, 0)
    assert sec.fetch_ownership(p, date(2026, 10, 30), from_day=date(2026, 10, 28),
                               **QUIET).files_stored == 0  # fmt: skip


PAGE = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
SETS = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"


@respx.mock
def test_a_quarterly_data_set_is_fetched_once_its_quarter_has_ended_and_it_is_published(
    sec_env, archives, quarter_zip
):
    p, _ = sec_env
    archives({"2026q3": {"SUBMISSION": [{"ACCESSION_NUMBER": "a"}]}})
    page = respx.get(PAGE).mock(return_value=httpx.Response(200, text=(
        '<a href="/files/structureddata/data/insider-transactions-data-sets/2026q3_form345.zip">'
        '</a><a href="/files/structureddata/data/insider-transactions-data-sets/'
        '2026q4_form345.zip">2026 Q4</a>')))  # fmt: skip
    tables = {t: [{"ACCESSION_NUMBER": "b"}] for t in ("SUBMISSION", "REPORTINGOWNER",
                                                      "NONDERIV_TRANS", "FOOTNOTES")}  # fmt: skip
    q4 = respx.get(f"{SETS}/2026q4_form345.zip").mock(
        return_value=httpx.Response(200, content=quarter_zip(tables))
    )
    q1 = respx.get(re.compile(r".*/2027q1_form345\.zip$")).mock(return_value=httpx.Response(404))
    assert sec.fetch_ownership(p, date(2026, 12, 15), quarterly=True, **QUIET).requests == 0
    report = sec.fetch_ownership(p, date(2027, 2, 15), quarterly=True, **QUIET)
    assert (page.call_count, q4.call_count, q1.call_count) == (1, 1, 0)  # Q1 2027 not ended
    assert report.files_stored == 1
    entry = Manifest(p.manifest).find_original("sec_insider_bulk", "2026q4")
    assert entry.path == "sec/insider/2026q4_form345.zip"
    assert sec.fetch_ownership(p, date(2027, 2, 15), quarterly=True, **QUIET).requests == 0
    report = sec.fetch_ownership(p, date(2027, 4, 15), quarterly=True, **QUIET)
    assert (q1.call_count, report.files_stored, report.status) == (2, 0, "nothing_new")


@respx.mock
def test_a_broken_quarterly_data_set_is_not_stored(sec_env, archives):
    p, _ = sec_env
    archives({"2026q3": {"SUBMISSION": [{"ACCESSION_NUMBER": "a"}]}})
    respx.get(PAGE).mock(return_value=httpx.Response(200, text=""))
    respx.get(f"{SETS}/2026q4_form345.zip").mock(return_value=httpx.Response(200, content=b"PK?"))
    with pytest.raises(ValueError, match="2026q4: not a readable zip"):
        sec.fetch_ownership(p, date(2027, 2, 15), quarterly=True, **QUIET)
    assert not list(p.sec_insider.glob("2026q4*"))
    assert Manifest(p.manifest).find_original("sec_insider_bulk", "2026q4") is None
