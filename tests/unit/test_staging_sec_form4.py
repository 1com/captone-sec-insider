"""Step 2: typed staging of the SEC tables (FR-001 – FR-005, W1, W2)."""

import duckdb
import pytest
from conftest import holding, line, note, owner, sub

from sentinel import db
from sentinel.staging import sec_form4 as stage

TABLES = [
    "submission",
    "reportingowner",
    "nonderiv_trans",
    "nonderiv_holding",
    "deriv_trans",
    "deriv_holding",
    "footnotes",
    "owner_signature",
]
A = "0000036270-19-000001"


@pytest.fixture
def quarters():
    return {
        "2019q1": {
            "SUBMISSION": [sub(A, cik="0000036270"), sub("dup", date="28-MAR-2019")],
            "REPORTINGOWNER": [owner(A, ocik="0001234567")],
            "NONDERIV_TRANS": [
                line(A, "1", EQUITY_SWAP_INVOLVED="0", after="1500"),
                line(A, "2", tdate="31-FOO-2019", shares="F1"),
            ],
            "NONDERIV_HOLDING": [holding(A, "1")],
            "FOOTNOTES": [note(A, "F1", 'He said "bought" — quoting is off')],
            "OWNER_SIGNATURE": [
                {
                    "ACCESSION_NUMBER": A,
                    "OWNERSIGNATURENAME": "X",
                    "OWNERSIGNATUREDATE": "14-MAR-2019",
                }
            ],
        },
        "2023q1": {
            "SUBMISSION": [sub("b", date="15-FEB-2023", aff="1"), sub("dup", date="28-MAR-2019")],
            "REPORTINGOWNER": [owner("b")],
            "NONDERIV_TRANS": [line("b", "1", tdate="13-FEB-2023")],
        },
    }


@pytest.fixture
def staged(archives, quarters, tmp_data):
    archives(quarters)
    con = db.connect(tmp_data)
    report = stage.stage_all(con, stage.stored_archives(tmp_data))
    yield con, report
    con.close()


def test_all_tables_exist_and_counts_match_the_files(staged):
    con, report = staged
    rows = con.execute(
        "select table_name, quarter, rows_expected, rows_loaded from stg_sec_form4.load_report"
    ).fetchall()
    assert {r[0] for r in rows} == set(TABLES)
    assert len(rows) == 16
    assert all(r[2] == r[3] for r in rows)
    assert report.mismatches == []
    counts = {(r[0], r[1]): r[3] for r in rows}
    assert counts[("submission", "2019q1")] == 2
    assert counts[("nonderiv_trans", "2019q1")] == 2
    assert counts[("deriv_trans", "2023q1")] == 0
    assert report.total_rows == sum(counts.values())


def test_columns_are_typed(staged):
    con, _ = staged
    types = {
        (t, c): ty
        for t, c, ty in con.execute(
            "select table_name, column_name, data_type from information_schema.columns "
            "where table_schema = 'stg_sec_form4'"
        ).fetchall()
    }
    assert types[("submission", "filing_date")] == "DATE"
    assert types[("nonderiv_trans", "trans_shares")] == "DOUBLE"
    assert types[("nonderiv_trans", "equity_swap_involved")] == "BOOLEAN"
    assert types[("submission", "aff10b5one")] == "BOOLEAN"
    assert types[("owner_signature", "ownersignaturedate")] == "DATE"
    assert types[("footnotes", "footnote_txt")] == "VARCHAR"
    row = con.execute(
        "select issuercik, filing_date::VARCHAR from stg_sec_form4.submission "
        "where accession_number = ?",
        [A],
    ).fetchone()
    assert row == ("36270", "2019-03-15")
    assert (
        con.execute(
            "select rptownercik from stg_sec_form4.reportingowner where quarter = '2019q1'"
        ).fetchone()[0]
        == "1234567"
    )
    swap, after = con.execute(
        "select equity_swap_involved, shrs_ownd_folwng_trans from stg_sec_form4.nonderiv_trans "
        "where nonderiv_trans_sk = '1' and quarter = '2019q1'"
    ).fetchone()
    assert swap is False and after == 1500.0


def test_text_with_quotes_survives(staged):
    con, _ = staged
    assert con.execute("select footnote_txt from stg_sec_form4.footnotes").fetchone()[0] == (
        'He said "bought" — quoting is off'
    )


def test_failed_conversions_become_null_with_the_raw_text_kept(staged):
    con, report = staged
    assert con.execute(
        "select trans_date, trans_shares from stg_sec_form4.nonderiv_trans "
        "where nonderiv_trans_sk = '2'"
    ).fetchone() == (None, None)
    issues = con.execute(
        "select table_name, quarter, src_row, column_name, raw_value "
        "from stg_sec_form4.conversion_issue "
        "order by column_name"
    ).fetchall()
    assert issues == [
        ("nonderiv_trans", "2019q1", 2, "trans_date", "31-FOO-2019"),
        ("nonderiv_trans", "2019q1", 2, "trans_shares", "F1"),
    ]
    assert report.issues_by_column[("nonderiv_trans", "trans_shares")] == 1


def test_checkbox_column_exists_for_every_year_and_is_null_before_2023(staged):
    con, _ = staged
    rows = dict(
        con.execute(
            "select quarter, list(aff10b5one) from stg_sec_form4.submission group by quarter"
        ).fetchall()
    )
    assert rows["2019q1"] == [None, None]
    assert sorted(rows["2023q1"], key=str) == [None, True]
    drift = stage.drift_report(con)
    assert drift["submission"]["aff10b5one"] == ["2023q1"]
    assert drift["submission"]["filing_date"] == ["2019q1", "2023q1"]


def test_quarter_and_source_row_are_a_unique_key(staged):
    con, _ = staged
    for table in TABLES:
        total, distinct = con.execute(
            f"select count(*), count(distinct (quarter, src_row)) from stg_sec_form4.{table}"
        ).fetchone()
        assert total == distinct, table


def test_duplicate_accessions_across_quarters_are_kept_in_staging(staged):
    con, _ = staged
    assert con.execute(
        "select list(quarter order by quarter) from stg_sec_form4.submission "
        "where accession_number = 'dup'"
    ).fetchone()[0] == ["2019q1", "2023q1"]


def test_rebuilding_gives_identical_rows(staged, tmp_data):
    con, _ = staged

    def snapshot():
        return {
            t: con.execute(f"select * from stg_sec_form4.{t} order by quarter, src_row").fetchall()
            for t in TABLES + ["conversion_issue"]
        }

    first = snapshot()
    stage.stage_all(con, stage.stored_archives(tmp_data))
    assert snapshot() == first


def test_unexpected_column_is_an_error(tmp_data, monkeypatch, archives, quarters):
    import conftest

    monkeypatch.setitem(conftest.HEADERS, "FOOTNOTES", [*conftest.HEADERS["FOOTNOTES"], "SURPRISE"])
    archives(quarters)
    con = db.connect(tmp_data)
    with pytest.raises(stage.StageError, match="SURPRISE"):
        stage.stage_all(con, stage.stored_archives(tmp_data))
    con.close()


def test_a_failed_rebuild_keeps_the_previous_tables(staged, tmp_data, monkeypatch):
    con, _ = staged
    before = con.execute("select count(*) from stg_sec_form4.submission").fetchone()[0]
    real = stage._load_one

    def fail_in_2023(con, quarter, *args):
        if quarter == "2023q1":
            raise stage.StageError("boom")
        real(con, quarter, *args)

    monkeypatch.setattr(stage, "_load_one", fail_in_2023)
    with pytest.raises(stage.StageError, match="boom"):
        stage.stage_all(con, stage.stored_archives(tmp_data))
    assert con.execute("select count(*) from stg_sec_form4.submission").fetchone()[0] == before
    assert not con.execute(
        "select table_name from information_schema.tables "
        f"where starts_with(table_name, '{stage.SHADOW}')"
    ).fetchall()


def test_a_read_only_connection_reads_but_cannot_write(staged, tmp_data):
    con, _ = staged
    con.close()
    reader = db.connect(tmp_data, read_only=True)
    assert reader.execute("select count(*) from stg_sec_form4.submission").fetchone()[0] == 4
    with pytest.raises(duckdb.Error, match="read-only"):
        reader.execute("delete from stg_sec_form4.submission")
    reader.close()
