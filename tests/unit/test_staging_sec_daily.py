"""Layer 2 with daily SEC files: index rows join the bulk filings, new registrants are added from
their own documents, and each company's financial values come from its newest document. The daily
update applies only a day's new files, with the same result as staging in full (research R10)."""

import io
import json
import zipfile
from datetime import date

from sentinel import build, db
from sentinel.raw.manifest import Manifest, store_bytes, store_gz
from sentinel.staging import sec_filings, sec_xbrl
from sentinel.update import verify as verifier

QUIET = {"echo": lambda s: None}
INDEX_HEAD = "CIK|Company Name|Form Type|Date Filed|File Name\n" + "-" * 80 + "\n"


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, doc in entries.items():
            z.writestr(name, json.dumps(doc))
    return buf.getvalue()


def _store(p, source, rel, key, data, when, gz=False):
    book = Manifest(p.manifest)
    (store_gz if gz else store_bytes)(p, book, source, rel, key, data, "https://x.test")
    # the fetch time decides which document is newest
    lines = p.manifest.read_text().splitlines()
    entry = json.loads(lines[-1]) | {"fetched_at": when}
    p.manifest.write_text("\n".join([*lines[:-1], json.dumps(entry)]) + "\n")


def _company(cik, accessions, forms):
    return {"cik": cik, "name": f"Company {cik}", "sic": "3571", "entityType": "operating",
            "filings": {"recent": {"accessionNumber": accessions, "form": forms,
                                   "filingDate": ["2026-10-20"] * len(forms),
                                   "reportDate": ["2026-09-30"] * len(forms)}}}  # fmt: skip


def test_index_rows_and_new_registrants_join_the_bulk_filings(tmp_data):
    p = tmp_data
    _store(p, "sec_company", "sec/company/submissions.zip", "submissions",
           _zip({"CIK0000000042.json": _company("42", ["0000000042-26-000001"], ["10-Q"])}),
           "2026-10-23T08:00:00Z")  # fmt: skip
    _store(p, "sec_submissions_cik", "sec/submissions/2026-10-29/CIK0000000077.json.gz",
           "77/2026-10-29", json.dumps(_company("77", ["0000000077-26-000001"], ["S-1"])).encode(),
           "2026-10-29T22:00:00Z", gz=True)  # fmt: skip
    index = INDEX_HEAD + "\n".join([
        "42|COMPANY 42|10-Q|20261028|edgar/data/42/0000000042-26-000001.txt",  # in the base
        "42|COMPANY 42|8-K|20261028|edgar/data/42/0000000042-26-000002.txt",   # new
        "77|COMPANY 77|S-1|20261028|edgar/data/77/0000000077-26-000001.txt",   # in its document
        "9001|DOE JANE|4|20261028|edgar/data/9001/0000009001-26-000001.txt",   # not a company
    ]) + "\n"  # fmt: skip
    _store(p, "sec_index", "sec/index/2026/master.20261028.idx.gz", "master/20261028",
           index.encode(), "2026-10-29T22:00:00Z", gz=True)  # fmt: skip
    con = db.connect(p)
    counts = sec_filings.stage(con, p, **QUIET)
    assert (counts["new_filers"], counts["daily_filings"]) == (1, 1)
    rows = con.execute("select cik, form, origin from stg_sec_filings.filing order by 1, 2")
    assert rows.fetchall() == [("42", "10-Q", "bulk"), ("42", "8-K", "daily"),
                               ("77", "S-1", "bulk")]  # fmt: skip


def test_a_companys_financial_values_come_from_its_newest_document(tmp_data):
    p = tmp_data

    def doc(*values):
        facts = [{"end": end, "val": v, "filed": filed, "accn": a, "form": "10-Q", "fp": "Q1",
                  "fy": 2026} for end, v, filed, a in values]  # fmt: skip
        return {"cik": 42, "facts": {"us-gaap": {"Assets": {"units": {"USD": facts}}}}}

    old = ("2026-03-31", 100, "2026-05-01", "a1")
    _store(p, "sec_company", "sec/company/companyfacts.zip", "companyfacts",
           _zip({"CIK0000000042.json": doc(old), "CIK0000000043.json": doc(old)}),
           "2026-10-23T08:00:00Z")  # fmt: skip
    _store(p, "sec_companyfacts_cik", "sec/companyfacts/2026-10-29/CIK0000000042.json.gz",
           "42/2026-10-29", json.dumps(doc(old, ("2026-09-30", 120, "2026-10-28", "a2"))).encode(),
           "2026-10-29T22:00:00Z", gz=True)  # fmt: skip
    con = db.connect(p)
    sec_xbrl.stage(con, p, **QUIET)
    got = con.execute("select cik, value, filed, raw_file like 'sec/companyfacts/%' "
                      "from stg_sec_xbrl.fact order by 1, 3").fetchall()  # fmt: skip
    assert got == [("42", 100.0, date(2026, 5, 1), True), ("42", 120.0, date(2026, 10, 28), True),
                   ("43", 100.0, date(2026, 5, 1), False)]  # fmt: skip


def _facts(cik, *values):
    facts = [{"end": end, "val": v, "filed": filed, "accn": a, "form": "10-Q", "fp": "Q1",
              "fy": 2026} for end, v, filed, a in values]  # fmt: skip
    return {"cik": cik, "facts": {"us-gaap": {"Assets": {"units": {"USD": facts}}}}}


def _index(p, day: str, lines: list[str]) -> None:
    when = f"{day[:4]}-{day[4:6]}-{day[6:]}T22:00:00Z"
    _store(p, "sec_index", f"sec/index/2026/master.{day}.idx.gz", f"master/{day}",
           (INDEX_HEAD + "\n".join(lines) + "\n").encode(), when, gz=True)  # fmt: skip


def _doc(p, source, cik, day, doc):
    folder = "submissions" if source == "sec_submissions_cik" else "companyfacts"
    _store(p, source, f"sec/{folder}/{day}/CIK{int(cik):010d}.json.gz", f"{cik}/{day}",
           json.dumps(doc).encode(), f"{day}T22:30:00Z", gz=True)  # fmt: skip


def test_a_days_new_files_alone_give_the_same_tables_as_staging_in_full(tmp_data, monkeypatch):
    p = tmp_data
    monkeypatch.setitem(build.LAYERS, "staging", {"sec_filings": sec_filings.stage,
                                                  "sec_xbrl": sec_xbrl.stage})  # fmt: skip
    old = ("2026-03-31", 100, "2026-05-01", "a1")
    _store(p, "sec_company", "sec/company/submissions.zip", "submissions",
           _zip({"CIK0000000042.json": _company("42", ["0000000042-26-000001"], ["10-Q"])}),
           "2026-10-23T08:00:00Z")  # fmt: skip
    _store(p, "sec_company", "sec/company/companyfacts.zip", "companyfacts",
           _zip({"CIK0000000042.json": _facts(42, old), "CIK0000000043.json": _facts(43, old)}),
           "2026-10-23T08:00:00Z")  # fmt: skip
    _doc(p, "sec_submissions_cik", "77", "2026-10-28",
         _company("77", ["0000000077-26-000001"], ["S-1"]))  # fmt: skip
    _doc(p, "sec_companyfacts_cik", "42", "2026-10-28",
         _facts(42, old, ("2026-09-30", 110, "2026-10-28", "a2")))  # fmt: skip
    _index(p, "20261028", ["42|COMPANY 42|8-K|20261028|edgar/data/42/0000000042-26-000002.txt"])
    con = db.connect(p)
    build.run(con, p, "staging", echo=QUIET["echo"])

    # day 29: an index; a newer document of registrant 77 and a new registrant 88; newer financial
    # values of 42 and of 43, which only the bulk file held so far
    accessions = ["0000000077-26-000001", "0000000077-26-000002"]
    _doc(p, "sec_submissions_cik", "77", "2026-10-29", _company("77", accessions, ["S-1", "S-1/A"]))
    _doc(p, "sec_submissions_cik", "88", "2026-10-29",
         _company("88", ["0000000088-26-000001"], ["10-12B"]))  # fmt: skip
    _doc(p, "sec_companyfacts_cik", "42", "2026-10-29",
         _facts(42, old, ("2026-09-30", 120, "2026-10-29", "a3")))  # fmt: skip
    _doc(p, "sec_companyfacts_cik", "43", "2026-10-29",
         _facts(43, ("2026-09-30", 7, "2026-10-29", "b1")))  # fmt: skip
    _index(p, "20261029", [
        "42|COMPANY 42|8-K|20261029|edgar/data/42/0000000042-26-000003.txt",
        "77|COMPANY 77|S-1/A|20261029|edgar/data/77/0000000077-26-000002.txt",  # in its document
        "77|COMPANY 77|8-K|20261029|edgar/data/77/0000000077-26-000003.txt",
        "88|COMPANY 88|8-K|20261029|edgar/data/88/0000000088-26-000002.txt",
    ])  # fmt: skip
    # a missed day's index arriving late, listing a filing already staged from the 28th's index:
    # staging in full takes it from the earliest index
    _index(p, "20261027", ["42|COMPANY 42|8-K|20261027|edgar/data/42/0000000042-26-000002.txt"])
    said = []
    build.run(con, p, "staging", echo=said.append, incremental=True)
    assert not any("filers read" in s or "companies read" in s for s in said)  # no base re-read
    filings = con.execute("select cik, form, origin from stg_sec_filings.filing order by all")
    assert filings.fetchall() == [
        ("42", "10-Q", "bulk"), ("42", "8-K", "daily"), ("42", "8-K", "daily"),
        ("77", "8-K", "daily"), ("77", "S-1", "bulk"), ("77", "S-1/A", "bulk"),
        ("88", "10-12B", "bulk"), ("88", "8-K", "daily")]  # fmt: skip
    values = con.execute("select cik, value from stg_sec_xbrl.fact order by all").fetchall()
    assert values == [("42", 100.0), ("42", 120.0), ("43", 7.0)]
    con.close()
    assert verifier.verify(p, layers=("staging",), echo=QUIET["echo"]) == []


def test_a_new_bulk_file_or_missing_tables_mean_staging_in_full(tmp_data):
    p = tmp_data
    _store(p, "sec_company", "sec/company/submissions.zip", "submissions",
           _zip({"CIK0000000042.json": _company("42", ["0000000042-26-000001"], ["10-Q"])}),
           "2026-10-23T08:00:00Z")  # fmt: skip
    _store(p, "sec_company", "sec/company/companyfacts.zip", "companyfacts",
           _zip({"CIK0000000042.json": _facts(42, ("2026-03-31", 1, "2026-05-01", "a1"))}),
           "2026-10-23T08:00:00Z")  # fmt: skip
    con = db.connect(p)
    staged = {"sec/company/submissions.zip", "sec/company/companyfacts.zip"}
    assert sec_filings.stage_new(con, p, staged, **QUIET) is None  # no tables yet
    assert sec_xbrl.stage_new(con, p, staged, **QUIET) is None
    sec_filings.stage(con, p, **QUIET)
    sec_xbrl.stage(con, p, **QUIET)
    assert sec_filings.stage_new(con, p, staged, **QUIET) is not None
    assert sec_xbrl.stage_new(con, p, staged, **QUIET) is not None
    for name in ("submissions", "companyfacts"):
        _store(p, "sec_company", f"sec/company/2026-10-29/{name}.zip", f"{name}/2026-10-29",
               _zip({}), "2026-10-29T21:00:00Z")  # fmt: skip
    assert sec_filings.stage_new(con, p, staged, **QUIET) is None
    assert sec_xbrl.stage_new(con, p, staged, **QUIET) is None
