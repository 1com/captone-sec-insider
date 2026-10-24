"""Step 6: signal-filing headers, with SIC at T and the acceptance time (FR-020, FR-021)."""

import stat
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
import respx
from conftest import line, owner, sub

from sentinel.ingest import sec_headers
from sentinel.ingest.http import RateLimiter, RetryPolicy, SecForbidden, make_client
from sentinel.ingest.manifest import read_all

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "edgar_header_form4.txt").read_text()
ACC = "0001225208-19-010527"
URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{acc}-index-headers.html"
SGML_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{acc}.hdr.sgml"
SGML = FIXTURE[FIXTURE.index("<SEC-HEADER>") : FIXTURE.index("-->")]  # the bare .hdr.sgml


def url(cik, acc, pattern=URL):
    return pattern.format(cik=cik, nodash=acc.replace("-", ""), acc=acc)


def without_sic(text):
    return "\n".join(
        x for x in text.split("\n") if "ASSIGNED-SIC" not in x and "INDUSTRIAL CLASS" not in x
    )


def test_parse_header():
    h = sec_headers.parse_header(FIXTURE)
    assert (h.sic, h.sic_label) == ("2810", "INDUSTRIAL INORGANIC CHEMICALS")
    assert h.accepted_at_et == datetime(2019, 7, 26, 11, 48, 41)
    assert (h.form_type, h.filed_as_of, h.issuer_cik) == ("4", date(2019, 7, 26), "2969")


def test_a_header_without_sic_parses_with_sic_null():
    h = sec_headers.parse_header(without_sic(FIXTURE))
    assert (h.sic, h.sic_label) == (None, None)
    assert h.accepted_at_et == datetime(2019, 7, 26, 11, 48, 41)


def test_a_bare_sgml_header_parses_without_the_industry_name():
    h = sec_headers.parse_header(SGML, expect_accession=ACC)
    assert (h.sic, h.sic_label, h.issuer_cik) == ("2810", None, "2969")
    assert h.accepted_at_et == datetime(2019, 7, 26, 11, 48, 41)


def test_a_page_that_is_not_a_header_is_a_parse_error():
    with pytest.raises(sec_headers.HeaderParseError):
        sec_headers.parse_header("<html><body>Not found</body></html>")


def test_a_header_for_another_filing_is_a_parse_error():
    with pytest.raises(sec_headers.HeaderParseError, match="accession"):
        sec_headers.parse_header(FIXTURE, expect_accession="0000000000-00-000000")


def test_the_header_limiter_targets_eight_per_second(params):
    assert sec_headers.header_limiter(params)._interval == pytest.approx(1 / 8)


def ceo_buy(acc, date_str, cik):
    return (
        sub(acc, date=date_str, cik=cik),
        owner(acc, ocik=f"9{cik}", rel="Officer", title="CEO"),
        line(acc, "1", tdate=date_str, shares="3000", price="50"),
    )


@pytest.fixture
def events(archives, pipeline):
    """Solo CEO buys (B1): one in 2011, before the labelled window, and two from 2012."""
    filings = [
        ceo_buy("ev-2011", "15-DEC-2011", "100"),
        ceo_buy("ev-2012", "16-JAN-2012", "200"),
        ceo_buy(ACC, "26-JUL-2019", "2969"),
    ]
    archives(
        {
            "2019q3": {
                "SUBMISSION": [f[0] for f in filings],
                "REPORTINGOWNER": [f[1] for f in filings],
                "NONDERIV_TRANS": [f[2] for f in filings],
            }
        }
    )
    return pipeline(until="prelim")


def test_only_signal_filings_from_the_labelled_window_are_selected(events, params, tmp_data):
    targets = sec_headers.signal_accessions(events, params, tmp_data)
    assert [(t.accession, t.issuer_cik) for t in targets] == [
        (ACC, "2969"),
        ("ev-2012", "200"),
    ]


@pytest.fixture
def net():
    return {
        "client": make_client("Test User test@example.com", 5),
        "limiter": RateLimiter(5, 10, clock=lambda: 0.0, sleep=lambda s: None),
        "policy": RetryPolicy(2, 0.0, 0.0, sleep=lambda s: None),
    }


def fetch(tmp_data, params, net, targets, **kw):
    return sec_headers.fetch_headers(
        tmp_data, params, net["client"], net["limiter"], net["policy"], targets, **kw
    )


@respx.mock
def test_fetch_stores_read_only_files_and_records_failures(events, params, tmp_data, net):
    good = respx.get(url("2969", ACC)).mock(return_value=httpx.Response(200, text=FIXTURE))
    missing = respx.get(url("200", "ev-2012")).mock(return_value=httpx.Response(404))
    respx.get(url("200", "ev-2012", SGML_URL)).mock(return_value=httpx.Response(404))
    targets = sec_headers.signal_accessions(events, params, tmp_data)

    report = fetch(tmp_data, params, net, targets)
    assert report.stored == 1
    assert [(acc, reason) for acc, reason in report.failed] == [("ev-2012", "HTTP 404")]
    path = tmp_data.sec_headers / "2019" / f"{ACC}.txt"
    assert path.read_text() == FIXTURE
    assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    entries = [e for e in read_all(tmp_data.manifest) if e.source == sec_headers.SOURCE]
    assert [(e.key, e.path, e.role) for e in entries] == [
        (ACC, f"sec/headers/2019/{ACC}.txt", "original")
    ]

    sec_headers.record_failures(events, report.failed)
    assert sec_headers.signal_accessions(events, params, tmp_data) == []
    retry = sec_headers.signal_accessions(events, params, tmp_data, include_failed=True)
    assert [t.accession for t in retry] == ["ev-2012"]
    fetch(tmp_data, params, net, retry)
    assert (good.call_count, missing.call_count) == (1, 2)  # the stored header is never refetched


@respx.mock
def test_fetch_failures_survive_a_rebuild_from_raw_files(events, params, tmp_data, net):
    """An offline rebuild has only data/raw: the failures are kept in failures.csv beside the
    headers, and a later success removes them."""
    respx.get(url("2969", ACC)).mock(return_value=httpx.Response(200, text=FIXTURE))
    missing = respx.get(url("200", "ev-2012")).mock(return_value=httpx.Response(404))
    respx.get(url("200", "ev-2012", SGML_URL)).mock(return_value=httpx.Response(404))
    fetch(tmp_data, params, net, sec_headers.signal_accessions(events, params, tmp_data))
    events.execute("drop table if exists core.header_failure")
    sec_headers.load_headers(events, tmp_data)
    assert events.execute("select accession, reason from core.header_failure").fetchall() == [
        ("ev-2012", "HTTP 404")
    ]

    missing.mock(return_value=httpx.Response(200, text=FIXTURE.replace(ACC, "ev-2012")))
    retry = sec_headers.signal_accessions(events, params, tmp_data, include_failed=True)
    fetch(tmp_data, params, net, retry)
    assert sec_headers.read_failures(tmp_data) == {}
    sec_headers.load_headers(events, tmp_data)
    assert events.execute("select count(*) from core.header_failure").fetchone()[0] == 0


@respx.mock
def test_a_missing_index_page_falls_back_to_the_sgml_header(events, params, tmp_data, net):
    respx.get(url("2969", ACC)).mock(return_value=httpx.Response(404))
    sgml = respx.get(url("2969", ACC, SGML_URL)).mock(return_value=httpx.Response(200, text=SGML))
    respx.get(url("200", "ev-2012")).mock(return_value=httpx.Response(500))

    report = fetch(tmp_data, params, net, sec_headers.signal_accessions(events, params, tmp_data))
    assert report.stored == 1 and sgml.call_count == 1
    assert [acc for acc, _ in report.failed] == ["ev-2012"]  # only a 404 falls back
    assert (tmp_data.sec_headers / "2019" / f"{ACC}.txt").read_text() == SGML
    [entry] = [e for e in read_all(tmp_data.manifest) if e.source == sec_headers.SOURCE]
    assert entry.url == url("2969", ACC, SGML_URL)


@respx.mock
def test_a_page_that_does_not_parse_is_not_stored(events, params, tmp_data, net):
    respx.get(url("2969", ACC)).mock(return_value=httpx.Response(200, text="<html>busy</html>"))
    respx.get(url("200", "ev-2012")).mock(
        return_value=httpx.Response(200, text=FIXTURE.replace(ACC, "ev-2012"))
    )
    report = fetch(tmp_data, params, net, sec_headers.signal_accessions(events, params, tmp_data))
    assert [acc for acc, _ in report.failed] == [ACC]
    assert report.failed[0][1].startswith("parse:")
    assert not list(tmp_data.sec_headers.rglob(f"{ACC}*"))


@respx.mock
def test_a_403_stops_the_fetch(events, params, tmp_data, net):
    respx.get(url("2969", ACC)).mock(return_value=httpx.Response(403))
    respx.get(url("200", "ev-2012")).mock(return_value=httpx.Response(200, text=FIXTURE))
    with pytest.raises(SecForbidden):
        fetch(tmp_data, params, net, sec_headers.signal_accessions(events, params, tmp_data))


@respx.mock
def test_limit_and_progress(events, params, tmp_data, net):
    respx.get(url("2969", ACC)).mock(return_value=httpx.Response(200, text=FIXTURE))
    seen = []
    report = fetch(
        tmp_data,
        params,
        net,
        sec_headers.signal_accessions(events, params, tmp_data),
        limit=1,
        on_progress=seen.append,
    )
    assert report.stored == 1 and seen == [1]


@respx.mock
def test_load_headers_builds_the_table_and_lists_parse_failures(events, params, tmp_data, net):
    respx.get(url("2969", ACC)).mock(return_value=httpx.Response(200, text=FIXTURE))
    respx.get(url("200", "ev-2012")).mock(
        return_value=httpx.Response(200, text=without_sic(FIXTURE).replace(ACC, "ev-2012"))
    )
    fetch(tmp_data, params, net, sec_headers.signal_accessions(events, params, tmp_data))
    n = sec_headers.load_headers(events, tmp_data)
    assert n == 2
    rows = events.execute(
        "select accession, issuer_cik, sic, sic_label, accepted_at_et, form_type, filed_as_of, "
        "raw_path from core.filing_header order by accession"
    ).fetchall()
    assert rows[0] == (
        ACC,
        "2969",
        "2810",
        "INDUSTRIAL INORGANIC CHEMICALS",
        datetime(2019, 7, 26, 11, 48, 41),
        "4",
        date(2019, 7, 26),
        f"sec/headers/2019/{ACC}.txt",
    )
    assert rows[1][0] == "ev-2012" and rows[1][2] is None  # no SIC: null, not a failure
    assert events.execute("select count(*) from core.header_failure").fetchone()[0] == 0


@pytest.mark.parametrize(
    "uncoded", [without_sic, lambda text: text.replace("2810", "0000")], ids=["none", "0000"]
)
@respx.mock
def test_d45_report_and_sheet_list_companies_without_sic(events, params, tmp_data, net, uncoded):
    """A header without SIC, or with EDGAR's "0000" (no code assigned, D51), counts as no SIC."""
    import csv

    from sentinel.core import audit

    respx.get(url("2969", ACC)).mock(return_value=httpx.Response(200, text=FIXTURE))
    respx.get(url("200", "ev-2012")).mock(
        return_value=httpx.Response(200, text=uncoded(FIXTURE).replace(ACC, "ev-2012"))
    )
    fetch(tmp_data, params, net, sec_headers.signal_accessions(events, params, tmp_data))
    sec_headers.load_headers(events, tmp_data)
    start = "2012-01-01"
    assert audit.no_sic_counts(events, start) == [(2012, "B1", 1, 1), (2019, "B1", 1, 0)]
    assert audit.make_no_sic_sheet(events, tmp_data.audits, start) == 1
    with (tmp_data.audits / "d45_no_sic.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["issuer_cik"], r["events"], r["groups"], r["verdict"]) for r in rows] == [
        ("200", "1", "B1", "")
    ]
    assert "CIK=200" in rows[0]["edgar_link"]
    with pytest.raises(audit.SheetsExist):
        audit.make_no_sic_sheet(events, tmp_data.audits, start)
    assert audit.summarize_no_sic(tmp_data.audits)["blank"] == 1
