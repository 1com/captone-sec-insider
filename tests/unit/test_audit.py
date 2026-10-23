"""Hand-audit sheets and their summary (FR-025, SC-004; contracts/audit-sheets.md)."""

import csv
from collections import Counter

import pytest
from conftest import line, note, owner, sub
from typer.testing import CliRunner

from sentinel import cli
from sentinel.core import audit

COLUMNS = {
    "entities": [
        "seed", "n", "issuer_cik", "issuer_name", "entity_id", "as_of", "members",
        "linking_accessions", "edgar_link", "verdict", "notes",
    ],
    "gates_excluded": [
        "seed", "n", "accession", "line_sk", "issuer_name", "filing_date", "security_title",
        "shares", "price", "deciding_gate", "cited_footnotes", "edgar_link", "verdict", "notes",
    ],
    "gates_kept": [
        "seed", "n", "accession", "issuer_name", "filing_date", "entity_role", "value_usd",
        "shares_before", "shares_after", "cited_footnotes", "edgar_link", "verdict", "notes",
    ],
}  # fmt: skip

PLAN = "Purchased under a Rule 10b5-1 trading plan adopted in 2018."
OFFER = "Bought in the issuer's underwritten public offering."


@pytest.fixture
def con(archives, pipeline):
    """12 excluded lines per stratum, 60 clean purchases and 3 joint-filer entities."""
    subs, owners, lines, notes = [], [], [], []

    def filing(acc, cik="100", owner_ciks=("9001",), **kw):
        subs.append(sub(acc, cik=cik))
        owners.extend(owner(acc, ocik=o) for o in owner_ciks)
        lines.append(line(acc, "1", **kw))

    for i in range(12):
        filing(f"g3-{i}", title="Series A Preferred Stock")
        filing(f"g4-{i}", TRANS_PRICEPERSHARE_FN="F1")
        notes.append(note(f"g4-{i}", "F1", PLAN))
        filing(f"g5-{i}", NATURE_OF_OWNERSHIP_FN="F2")
        notes.append(note(f"g5-{i}", "F2", OFFER))
        filing(f"g6a-{i}", tdate="01-JAN-2019")
        filing(f"g6b-{i}", shares="100")
    for i in range(60):
        filing(f"ok-{i}", cik=str(200 + i % 5), owner_ciks=(str(9100 + i),))
    for i in range(3):
        filing(f"joint-{i}", cik=str(300 + i), owner_ciks=("9501", "9502"))
    archives({"2019q1": {"SUBMISSION": subs, "REPORTINGOWNER": owners,
                         "NONDERIV_TRANS": lines, "FOOTNOTES": notes}})  # fmt: skip
    return pipeline(until="gates")


def read(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def header(path):
    with path.open(newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def test_sheets_have_the_contract_columns(con, tmp_data):
    counts = audit.make_sheets(con, tmp_data.audits)
    assert counts == {"entities": 3, "gates_excluded": 50, "gates_kept": 50}
    for sheet, columns in COLUMNS.items():
        assert header(tmp_data.audits / f"{sheet}.csv") == columns
    rows = read(tmp_data.audits / "gates_excluded.csv")
    assert {r["seed"] for r in rows} == {"2002"}
    assert [r["n"] for r in rows] == [str(i) for i in range(1, 51)]
    assert all(r["verdict"] == r["notes"] == "" for r in rows)
    acc = rows[0]["accession"].replace("-", "")
    assert rows[0]["edgar_link"] == f"https://www.sec.gov/Archives/edgar/data/100/{acc}/"


def test_the_same_seed_gives_the_same_sample(con, tmp_data):
    audit.make_sheets(con, tmp_data.audits)
    first = {p.name: p.read_bytes() for p in tmp_data.audits.glob("*.csv")}
    audit.make_sheets(con, tmp_data.audits, force=True)
    assert {p.name: p.read_bytes() for p in tmp_data.audits.glob("*.csv")} == first


def test_excluded_rows_are_stratified_by_deciding_gate(con, tmp_data):
    audit.make_sheets(con, tmp_data.audits)
    rows = read(tmp_data.audits / "gates_excluded.csv")
    gates = Counter(r["deciding_gate"] for r in rows)
    assert gates == {
        "g3_common": 10,
        "g4b_no_plan_fn": 10,
        "g5_no_offering_fn": 10,
        "g6a_timely_valued": 10,
        "g6b_min_value": 10,
    }
    g4 = next(r for r in rows if r["deciding_gate"] == "g4b_no_plan_fn")
    assert g4["cited_footnotes"] == f"F1: {PLAN}"


def test_entity_rows_list_members_and_linking_filings(con, tmp_data):
    audit.make_sheets(con, tmp_data.audits)
    rows = read(tmp_data.audits / "entities.csv")
    assert {r["entity_id"] for r in rows} == {"300:9501", "301:9501", "302:9501"}
    r = next(r for r in rows if r["entity_id"] == "300:9501")
    assert r["members"] == "9501: Owner 9501 (director) | 9502: Owner 9502 (director)"
    assert r["linking_accessions"] == "joint-0 (2019-03-15)"
    assert r["as_of"] == "2019-03-15"


def test_existing_sheets_are_kept_unless_forced(con, tmp_data):
    audit.make_sheets(con, tmp_data.audits)
    kept = tmp_data.audits / "gates_kept.csv"
    edited = kept.read_bytes().replace(b",,\r\n", b",correct,\r\n", 1)
    kept.write_bytes(edited)
    with pytest.raises(audit.SheetsExist):
        audit.make_sheets(con, tmp_data.audits)
    assert kept.read_bytes() == edited
    audit.make_sheets(con, tmp_data.audits, force=True)
    assert kept.read_bytes() != edited


def fill(path, verdicts):
    rows = read(path)
    for row, verdict in zip(rows, verdicts, strict=False):
        row["verdict"] = verdict
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_summary_counts_and_agreement(con, tmp_data):
    audit.make_sheets(con, tmp_data.audits)
    fill(tmp_data.audits / "gates_kept.csv", ["correct"] * 45 + ["wrong"] * 3 + ["unclear"])
    s = audit.summarize(tmp_data.audits)["gates_kept"]
    assert (s.correct, s.wrong, s.unclear, s.blank) == (45, 3, 1, 1)
    assert s.agreement == pytest.approx(45 / 48)
    assert audit.summarize(tmp_data.audits)["entities"].agreement is None


def test_summary_command_exits_1_while_any_verdict_is_blank(con, tmp_data, monkeypatch):
    audit.make_sheets(con, tmp_data.audits)
    monkeypatch.setattr(cli, "_paths", lambda: tmp_data)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["audit", "summary"])
    assert result.exit_code == cli.FAILED, result.output
    for sheet in COLUMNS:
        fill(tmp_data.audits / f"{sheet}.csv", ["correct"] * 50)
    result = runner.invoke(cli.app, ["audit", "summary"])
    assert result.exit_code == cli.OK, result.output
    assert "gates_kept" in result.output and "100.0%" in result.output
