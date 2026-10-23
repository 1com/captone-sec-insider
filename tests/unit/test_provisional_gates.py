import duckdb
import pytest

from sentinel.provisional.gates import GATES, apply_gates
from sentinel.provisional.load import load_archives


def sub(acc, date="15-MAR-2019", doc="4", cik="100", symbol="ABC", aff=""):
    return {
        "ACCESSION_NUMBER": acc,
        "FILING_DATE": date,
        "DOCUMENT_TYPE": doc,
        "ISSUERCIK": cik,
        "ISSUERNAME": "Abc Corp",
        "ISSUERTRADINGSYMBOL": symbol,
        "AFF10B5ONE": aff,
    }


def owner(acc, ocik="9001", rel="Director", title=""):
    return {
        "ACCESSION_NUMBER": acc,
        "RPTOWNERCIK": ocik,
        "RPTOWNER_RELATIONSHIP": rel,
        "RPTOWNER_TITLE": title,
    }


def line(
    acc,
    sk,
    title="Common Stock",
    code="P",
    ad="A",
    tdate="13-MAR-2019",
    shares="1000",
    price="20",
    **fn,
):
    row = {
        "ACCESSION_NUMBER": acc,
        "NONDERIV_TRANS_SK": sk,
        "SECURITY_TITLE": title,
        "TRANS_DATE": tdate,
        "TRANS_CODE": code,
        "TRANS_SHARES": shares,
        "TRANS_PRICEPERSHARE": price,
        "TRANS_ACQUIRED_DISP_CD": ad,
    }
    row.update(fn)
    return row


def note(acc, fid, txt):
    return {"ACCESSION_NUMBER": acc, "FOOTNOTE_ID": fid, "FOOTNOTE_TXT": txt}


@pytest.fixture
def run(tmp_path, quarter_zip, params):
    def go(subs, owners, lines, notes=(), checkbox=False):
        z = tmp_path / "2019q1_form345.zip"
        z.write_bytes(
            quarter_zip(
                {
                    "SUBMISSION": subs,
                    "REPORTINGOWNER": owners,
                    "NONDERIV_TRANS": lines,
                    "FOOTNOTES": list(notes),
                },
                checkbox=checkbox,
            )
        )
        con = duckdb.connect()
        load_archives(con, [("2019q1", z)], params)
        apply_gates(con, params)
        return con

    return go


def passes(con, acc, sk="1"):
    return con.execute(
        "select passes from p_gated where accession = ? and line_sk = ?", [acc, sk]
    ).fetchone()[0]


def clean(con):
    return {
        r[0]: r[1]
        for r in con.execute("select accession, value_usd from p_clean_filing").fetchall()
    }


def test_amendment_and_disposition_are_excluded(run):
    con = run(
        [sub("a"), sub("b", doc="4/A")],
        [owner("a"), owner("b")],
        [line("a", "1"), line("a", "2", ad="D"), line("b", "1")],
    )
    assert passes(con, "a", "1") and not passes(con, "a", "2") and not passes(con, "b")


def test_security_title(run):
    con = run(
        [sub("a"), sub("b")],
        [owner("a"), owner("b")],
        [
            line("a", "1", title="Class A Common Stock"),
            line("b", "1", title="Series A Preferred Stock"),
        ],
    )
    assert passes(con, "a") and not passes(con, "b")


def test_checkbox_excludes_whole_filing_only_when_ticked(run):
    subs = [sub("t1", aff="1"), sub("t2", aff="true"), sub("f", aff="0"), sub("blank", aff="")]
    accs = [s["ACCESSION_NUMBER"] for s in subs]
    lines = [line(a, sk) for a in accs for sk in ("1", "2")]
    con = run(subs, [owner(a) for a in accs], lines, checkbox=True)
    assert not passes(con, "t1", "1") and not passes(con, "t1", "2") and not passes(con, "t2")
    assert passes(con, "f") and passes(con, "blank")


def test_checkbox_absent_before_2023_counts_as_not_ticked(run):
    con = run([sub("a")], [owner("a")], [line("a", "1")], checkbox=False)
    assert passes(con, "a")


def test_footnotes_only_count_when_cited_by_the_line(run):
    con = run(
        [sub("a"), sub("b")],
        [owner("a"), owner("b")],
        [
            line("a", "1"),
            line("a", "2", NATURE_OF_OWNERSHIP_FN="F1"),
            line("b", "1", TRANS_PRICEPERSHARE_FN="F3, F2"),
        ],
        [
            note("a", "F1", "Purchased under a Rule 10b5-1 trading plan."),
            note("b", "F2", "Shares bought in the company's registered direct offering."),
        ],
    )
    assert passes(con, "a", "1")
    assert not passes(con, "a", "2")
    assert not passes(con, "b", "1")


def test_timeliness_window(run):
    con = run(
        [sub("a", date="15-MAR-2019"), sub("b"), sub("c")],
        [owner(x) for x in "abc"],
        [
            line("a", "1", tdate="13-FEB-2019"),  # 30 days
            line("b", "1", tdate="12-FEB-2019"),  # 31 days
            line("c", "1", tdate="16-MAR-2019"),
        ],
    )  # after filing
    assert passes(con, "a") and not passes(con, "b") and not passes(con, "c")


def test_price_standin_floor(run):
    con = run(
        [sub("a"), sub("b")],
        [owner("a"), owner("b")],
        [
            line("a", "1", price="2.00", shares="10000"),
            line("b", "1", price="1.99", shares="10000"),
        ],
    )
    assert passes(con, "a") and not passes(con, "b")


def test_filing_minimum_value(run, params):
    floor = params["registered"]["g6_min_value"]["value"]
    con = run(
        [sub("a"), sub("b")],
        [owner("a"), owner("b")],
        [
            line("a", "1", shares=str(floor / 10), price="10"),
            line("b", "1", shares=str(floor / 10 - 0.01), price="10"),
        ],
    )
    assert clean(con) == {"a": float(floor)}


def test_funnel_reconciles(run):
    con = run(
        [sub("a"), sub("b", doc="4/A")],
        [owner("a"), owner("b")],
        [line("a", "1"), line("a", "2", ad="D"), line("b", "1"), line("a", "3", title="Warrants")],
    )
    rows = con.execute(
        "select gate, rows_in, rows_out, rows_removed from p_funnel "
        "where unit = 'lines' order by step"
    ).fetchall()
    assert [r[0] for r in rows] == list(GATES)
    for (_, rin, rout, removed), nxt in zip(rows, rows[1:] + [None], strict=True):
        assert rin == rout + removed
        if nxt:
            assert nxt[1] == rout
    assert rows[0][1] == 4
