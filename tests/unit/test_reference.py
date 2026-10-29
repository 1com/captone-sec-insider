"""Layer 3a: companies, ticker history, the calendar and sectors, on synthetic staging tables."""

from datetime import date

import pytest

from sentinel import db
from sentinel.reference import build as ref

QUIET = {"echo": lambda s: None}


@pytest.fixture
def con(tmp_data):
    con = db.connect(tmp_data)
    con.execute(
        "create table stg_sec_filings.filer as select * from (values "
        "('1', 'Acme Corp', 'operating', '3571', true), "
        "('2', 'ASML HOLDING NV', 'other', '3559', true), "
        "('3', 'Hitachi Ltd', 'other', null, true), "
        "('4', 'Muni Income Fund', 'other', null, true), "
        "('5', 'Lending Corp BDC', 'other', null, true), "
        "('9', 'DOE JANE', 'other', null, false)"
        ") t(cik, name, entity_type, sic, is_company)"
    )
    for c in ("former_names", "sic_description", "category", "state_of_incorporation",
              "fiscal_year_end"):  # fmt: skip
        con.execute(f"alter table stg_sec_filings.filer add column {c} VARCHAR")
    con.execute(
        "create table stg_sec_filings.filing as select cik, form, filing_date::DATE as filing_date "
        "from (values ('1', '10-K', '2020-03-01'), ('1', '8-K', '2020-04-01'), "
        "('2', '20-F', '2021-02-01'), ('2', '6-K', '2021-07-01'), ('3', 'F-6', '2015-01-01'), "
        "('4', 'N-CSR', '2020-06-01'), ('4', 'N-2', '2019-01-01'), "
        "('5', 'N-2', '2019-01-01'), ('5', '10-K', '2020-03-01')) t(cik, form, filing_date)"
    )
    con.execute(
        "create table stg_sec_form4.submission as select * from (values "
        "('a1', '1', 'ACME', '2015-01-05'::DATE), ('a2', '1', 'ACME', '2019-06-03'::DATE), "
        "('a3', '1', 'ACM, ACMEW', '2016-02-01'::DATE)) "
        "t(accession_number, issuercik, issuertradingsymbol, filing_date)"
    )
    con.execute(
        "create table stg_sec_tickers.snapshot as select s::DATE as snapshot_date, cik, ticker, "
        "exchange, rank from (values ('2026-10-22', '1', 'ACME', 'Nasdaq', 3), "
        "('2026-10-22', '2', 'ASML', 'Nasdaq', 1), ('2026-10-22', '3', 'HTHIY', 'OTC', 2), "
        "('2026-10-21', '1', 'ACM', 'Nasdaq', 3)) t(s, cik, ticker, exchange, rank)"
    )
    return con


def test_companies_get_their_filer_type_and_fund_flags(con, tmp_data):
    ref.build_company(con, tmp_data, **QUIET)
    got = con.execute(
        "select cik, filer_type, is_fund, is_form4_issuer, tickers from ref.company order by cik"
    ).fetchall()
    assert got == [
        ("1", "us", False, True, ["ACME"]),
        ("2", "foreign", False, False, ["ASML"]),
        ("3", "non_reporting", False, False, ["HTHIY"]),  # trades OTC, files nothing periodic
        ("4", "non_reporting", True, False, None),  # a registered fund (N-CSR)
        ("5", "us", False, False, None),  # a BDC: N-2 but 10-Ks, not a fund (v5)
    ]  # the individual is not a company


def test_ticker_history_combines_form4_symbols_and_the_sec_lists(con, tmp_data):
    ref.build_ticker_history(con, tmp_data, **QUIET)
    got = con.execute(
        "select ticker, valid_from, valid_to, evidence from ref.ticker_history "
        "where cik = '1' order by evidence, ticker"
    ).fetchall()
    assert got == [
        ("ACM", date(2016, 2, 1), date(2016, 2, 1), "form4"),  # classes listed together
        ("ACME", date(2015, 1, 5), date(2019, 6, 3), "form4"),
        ("ACMEW", date(2016, 2, 1), date(2016, 2, 1), "form4"),
        ("ACM", date(2026, 10, 21), date(2026, 10, 21), "sec_list"),  # gone from the newest list
        ("ACME", date(2026, 10, 22), None, "sec_list"),  # still listed: open-ended
    ]


def test_symbols_are_normalised_and_placeholders_dropped():
    assert ref.split_symbols("brk.b; BRK/A , none") == ["BRK-B", "BRK-A"]
    assert ref.normalise("N/A") is None


def test_the_calendar_is_spys_sessions_and_sectors_come_from_sic(con, tmp_data):
    con.execute(
        "create table stg_yahoo.price as select 'SPY' as ticker, s::DATE as session, 1.0 as close "
        "from (values ('2009-12-31'), ('2010-01-04'), ('2010-01-05')) t(s)"
    )
    assert ref.build_calendar(con, tmp_data, **QUIET) == {"calendar": 2}
    assert con.execute("select max(session_no) from ref.calendar").fetchone() == (2,)
    ref.build_company(con, tmp_data, **QUIET)
    con.execute(
        "create table stg_market.sic_industry as select * from (values "
        "(12, 6, 'BusEq', 'Business Equipment', 3570, 3579)) "
        "t(scheme, industry_no, industry, description, sic_from, sic_to)"
    )
    ref.build_sector(con, tmp_data, **QUIET)
    got = dict(con.execute("select cik, sector from ref.sector").fetchall())
    assert got["1"] == "BusEq" and got["2"] == "Other"
