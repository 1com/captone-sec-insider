"""Form 3/4/5 filings as they are filed (US4): parsed into the quarterly data sets' tables, with the
same columns and types, from four real 28 October 2026 submissions (tests/fixtures/sec)."""

from datetime import date, datetime
from pathlib import Path

import pytest

from sentinel import db
from sentinel.raw.manifest import Manifest, store_gz
from sentinel.staging import sec_form4, sec_form4_daily

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sec"
FILES = {
    "0001437749-26-033807": "form4_purchase.txt",  # one purchase, one holding
    "0001204816-26-000057": "form4_checkbox.txt",  # five sales under a 10b5-1 plan
    "0001040470-26-000320": "form3.txt",  # a director's initial holdings
    "0001493152-26-048811": "form4a.txt",  # an amendment with a derivative line
}


def _store(p, accession: str, data: bytes) -> None:
    store_gz(p, Manifest(p.manifest), sec_form4_daily.SOURCE,
             f"sec/form4/2026/{accession}.txt.gz", accession, data, "stand-in")  # fmt: skip


@pytest.fixture
def staged(tmp_data):
    for accession, name in FILES.items():
        _store(tmp_data, accession, (FIXTURES / name).read_bytes())
    con = db.connect(tmp_data)
    report = sec_form4_daily.stage(con, tmp_data, echo=lambda s: None)
    yield con, report
    con.close()


def _rows(con, sql: str, *args) -> list[dict]:
    cur = con.execute(sql, list(args))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def _of(con, table: str, acc: str) -> list[dict]:
    """The rows of daily table `table` for accession `acc`, in table order."""
    return _rows(con, f"select * from stg_sec_form4_daily.{table} where accession_number = ? "
                      "order by src_row", acc)  # fmt: skip


def test_every_table_has_the_quarterly_columns_and_types(staged, tmp_data):
    con, report = staged
    sec_form4.stage_all(con, [])  # the quarterly tables, empty
    for table in sec_form4.TABLE_SPECS:
        name = table.lower()
        quarterly = con.execute(f"describe stg_sec_form4.{name}").fetchall()
        daily = con.execute(f"describe stg_sec_form4_daily.{name}").fetchall()
        assert [(c[0], c[1]) for c in daily[: len(quarterly)]] == [(c[0], c[1]) for c in quarterly]
        extra = [c[0] for c in daily[len(quarterly) :]]
        assert extra == (["filing_day", "raw_file", "accepted_at_et"] if name == "submission"
                         else ["filing_day", "raw_file"])  # fmt: skip
    assert report["documents"] == 4 and report["parse_issues"] == 0


def test_a_purchase_gives_its_submission_owner_line_holding_footnote_and_signature(staged):
    con, _ = staged
    acc = "0001437749-26-033807"
    (sub,) = _of(con, "submission", acc)
    assert sub["filing_date"] == date(2026, 10, 28)
    assert sub["period_of_report"] == date(2026, 10, 28)
    assert (sub["document_type"], sub["issuercik"]) == ("4", "1006830")
    assert sub["issuertradingsymbol"] == "CBKM"
    assert sub["aff10b5one"] is False
    assert sub["accepted_at_et"] == datetime(2026, 10, 28, 16, 57, 3)
    assert (sub["quarter"], sub["filing_day"]) == ("2026q4", date(2026, 10, 28))
    assert sub["raw_file"] == f"sec/form4/2026/{acc}.txt.gz"
    (own,) = _of(con, "reportingowner", acc)
    assert (own["rptownercik"], own["rptownername"]) == ("1341113", "WILLIAMS DEREK G")
    assert own["rptowner_relationship"] == "Officer"
    assert own["rptowner_title"] == "SVP, Retail Operations & Sales"
    assert (own["rptowner_city"], own["file_number"]) == ("LOUISVILLE", "033-79130")
    (line,) = _of(con, "nonderiv_trans", acc)
    assert line["nonderiv_trans_sk"] == "1"
    assert (line["trans_code"], line["trans_date"]) == ("P", date(2026, 10, 28))
    assert line["trans_shares"] == 100.0
    assert (line["trans_pricepershare"], line["trans_acquired_disp_cd"]) == (31.71, "A")
    assert line["equity_swap_involved"] is False
    assert (line["shrs_ownd_folwng_trans"], line["shrs_ownd_folwng_trans_fn"]) == (14603.8135, "F1")
    assert line["trans_pricepershare_fn"] is None
    assert line["direct_indirect_ownership"] == "D"
    (hold,) = _of(con, "nonderiv_holding", acc)
    assert (hold["shrs_ownd_folwng_trans"], hold["nature_of_ownership"]) == (100.0, "Child")
    (note,) = _of(con, "footnotes", acc)
    assert note["footnote_id"] == "F1"
    assert note["footnote_txt"] == "Includes shares acquired through dividend reinvestment plan"
    (sig,) = _of(con, "owner_signature", acc)
    assert sig["ownersignaturename"] == "/s/Derek Williams"
    assert sig["ownersignaturedate"] == date(2026, 10, 28)


def test_roles_are_written_as_in_the_data_sets_and_the_plan_checkbox_is_read(staged):
    con, _ = staged
    owners = dict(con.execute(
        "select accession_number, rptowner_relationship from stg_sec_form4_daily.reportingowner"
    ).fetchall())  # fmt: skip
    assert owners["0001204816-26-000057"] == "Director,Officer"  # 1/1/0/0
    assert owners["0001040470-26-000320"] == "Director"  # `true`
    assert owners["0001493152-26-048811"] == "Other"
    (txt,) = con.execute("select rptowner_txt from stg_sec_form4_daily.reportingowner "
                         "where accession_number = '0001493152-26-048811'").fetchone()  # fmt: skip
    assert txt == "Former director and officer"
    (plan,) = con.execute("select aff10b5one from stg_sec_form4_daily.submission "
                          "where accession_number = '0001204816-26-000057'").fetchone()  # fmt: skip
    assert plan is True
    sales = _of(con, "nonderiv_trans", "0001204816-26-000057")
    assert [s["nonderiv_trans_sk"] for s in sales] == ["1", "2", "3", "4", "5"]
    assert {s["trans_code"] for s in sales} == {"S"}
    assert [s["trans_pricepershare_fn"] for s in sales] == ["F1", "F2", "F3", "F4", "F5"]


def test_an_amendment_keeps_its_derivative_line_and_footnotes_without_values(staged):
    con, _ = staged
    acc = "0001493152-26-048811"
    (sub,) = _of(con, "submission", acc)
    assert (sub["document_type"], sub["date_of_orig_sub"]) == ("4/A", date(2026, 4, 24))
    (d,) = _of(con, "deriv_trans", acc)
    assert (d["security_title"], d["conv_exercise_price"]) == ("Series E Convertible Preferred "
                                                               "Stock", 1500.0)  # fmt: skip
    assert (d["trans_code"], d["equity_swap_trans_cd_fn"]) == ("A", "F2")
    assert (d["trans_pricepershare"], d["trans_pricepershare_fn"]) == (None, "F2")
    assert (d["excercise_date"], d["excercise_date_fn"]) == (None, "F3")
    assert (d["expiration_date"], d["expiration_date_fn"]) == (None, "F3")
    assert (d["undlyng_sec_title"], d["undlyng_sec_shares"], d["undlyng_sec_shares_fn"]) == (
        "Common Stock",
        0.0,
        "F1",
    )
    assert d["deemed_execution_date"] is None and d["trans_timeliness"] is None
    (form3,) = _of(con, "submission", "0001040470-26-000320")
    assert (form3["document_type"], form3["no_securities_owned"]) == ("3", False)


def test_a_value_that_cannot_be_converted_goes_to_parse_issue(tmp_data):
    text = (FIXTURES / "form4_purchase.txt").read_text()
    bad = text.replace("<value>31.71</value>", "<value>31,71</value>").replace(
        "<isOfficer>1</isOfficer>", "<isOfficer>yes</isOfficer>"
    )
    _store(tmp_data, "0001437749-26-033807", bad.encode())
    _store(tmp_data, "0000000000-26-000001", b"<SEC-DOCUMENT>not a filing</SEC-DOCUMENT>")
    con = db.connect(tmp_data)
    try:
        report = sec_form4_daily.stage(con, tmp_data, echo=lambda s: None)
        issues = _rows(con, "select accession_number, table_name, column_name, raw_value "
                            "from stg_sec_form4_daily.parse_issue order by 1, 2, 3")  # fmt: skip
        price = con.execute("select trans_pricepershare from stg_sec_form4_daily.nonderiv_trans"
                            ).fetchone()[0]  # fmt: skip
    finally:
        con.close()
    assert report["documents"] == 1 and report["parse_issues"] == 3
    assert issues[0]["accession_number"] == "0000000000-26-000001"  # unreadable: no rows at all
    assert issues[0]["table_name"] is None
    assert issues[1:] == [
        {"accession_number": "0001437749-26-033807", "table_name": "nonderiv_trans",
         "column_name": "trans_pricepershare", "raw_value": "31,71"},
        {"accession_number": "0001437749-26-033807", "table_name": "reportingowner",
         "column_name": "rptowner_relationship", "raw_value": "isOfficer=yes"},
    ]  # fmt: skip
    assert price is None
