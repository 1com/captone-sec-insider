import csv
from datetime import date

import duckdb
import pyarrow.parquet as pq

from sentinel.provisional.candidates import (
    CANDIDATE_COLUMNS,
    IssuerInfo,
    gap_mark,
    issuer_info,
    rank_candidates,
    start_year_table,
    write_outputs,
)
from sentinel.provisional.events import Event

START = date(2016, 1, 1)


def ev(cik, group, d):
    return Event(cik, group, d, 2 if group == "A" else 1, 150_000.0, ("x",), d >= START)


EVENTS = [
    ev("1", "B1", date(2024, 5, 1)),  # delisted, B1 only, newest
    ev("2", "A", date(2019, 2, 1)),  # delisted, cluster
    ev("3", "A", date(2022, 7, 1)),  # delisted, cluster, newer
    ev("4", "A", date(2023, 1, 9)),  # still active -> not a candidate
    ev("5", "A", date(2010, 3, 3)),  # delisted, only pre-2016
    ev("6", "A", date(2019, 2, 1)),  # delisted, ties with 2 on date -> CIK order
]
INFO = {c: IssuerInfo(f"Co {c}", f"T{c}", (f"T{c}",)) for c in "123456"}
ACTIVE = {"4"}


def ranked():
    return rank_candidates(EVENTS, INFO, ACTIVE, None, START)


def test_ranking_order():
    rows = ranked()
    assert [r["issuer_cik"] for r in rows] == ["3", "2", "6", "5", "1"]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["tier"] for r in rows] == [1, 1, 1, 1, 2]
    assert all(r["tiingo_match"] == "not_checked" for r in rows)
    assert list(rows[0]) == CANDIDATE_COLUMNS


def test_event_counts_and_labelled_window():
    by_cik = {r["issuer_cik"]: r for r in ranked()}
    assert by_cik["5"]["n_events_a"] == 1 and by_cik["5"]["n_events_labelled"] == 0
    assert by_cik["1"]["n_events_b1"] == 1 and by_cik["1"]["n_events_labelled"] == 1


def test_delisted_is_by_cik_even_if_ticker_now_reused():
    info = dict(INFO)
    info["2"] = IssuerInfo("Co 2", "T4", ("T4",))  # same ticker as active CIK 4
    assert "2" in {r["issuer_cik"] for r in rank_candidates(EVENTS, info, ACTIVE, None, START)}


def test_last_ticker_is_from_latest_filing_with_accession_tiebreak():
    con = duckdb.connect()
    con.execute("""
        create table p_submission as select * from (values
          ('0001-19-000001', date '2019-01-02', '4', '7', 'Old Name', 'abc'),
          ('0001-21-000009', date '2021-06-01', '3', '7', 'New Name', 'xyz.a'),
          ('0001-21-000010', date '2021-06-01', '4', '7', 'New Name', 'XYZ'),
          ('0001-22-000001', date '2022-01-05', '4', '7', 'New Name', 'NONE')
        ) t(accession, filing_date, document_type, issuer_cik, issuer_name, symbol_raw)
    """)
    info = issuer_info(con)["7"]
    assert info.last_ticker == "XYZ"
    assert info.all_tickers == ("ABC", "XYZ", "XYZ-A")
    assert info.name == "New Name"


def test_outputs_are_labelled_and_deterministic(tmp_path):
    for out in (tmp_path / "one", tmp_path / "two"):
        write_outputs(out, ranked(), EVENTS, [], "# summary\n", {"run": "meta"})
    names = sorted(p.name for p in (tmp_path / "one").iterdir())
    assert names == sorted(
        [
            "delisted_candidates_PROVISIONAL.csv",
            "events_PROVISIONAL.parquet",
            "funnel_PROVISIONAL.csv",
            "summary_PROVISIONAL.md",
            "run_PROVISIONAL.json",
        ]
    )
    a = (tmp_path / "one" / "delisted_candidates_PROVISIONAL.csv").read_bytes()
    assert a == (tmp_path / "two" / "delisted_candidates_PROVISIONAL.csv").read_bytes()
    with open(tmp_path / "one" / "delisted_candidates_PROVISIONAL.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0])[0] == "status"
    assert {r["status"] for r in rows} == {"PROVISIONAL"}
    events = pq.read_table(tmp_path / "one" / "events_PROVISIONAL.parquet")
    assert events.column_names[0] == "status"
    assert set(events.column("status").to_pylist()) == {"PROVISIONAL"}


def test_gap_marks():
    assert gap_mark(114, 100, 0.15) == ""
    assert gap_mark(116, 100, 0.15) == "CHECK"
    assert gap_mark(85, 100, 0.15) == ""
    assert gap_mark(101.1, 100, 0.01) == "CHECK"


def test_start_year_table():
    rows = {r["start_year"]: r for r in start_year_table(EVENTS, INFO, ACTIVE, None, [2006, 2016])}
    assert rows[2006]["events"] == 6 and rows[2006]["companies"] == 6
    assert rows[2016]["events"] == 5 and rows[2016]["companies"] == 5
    assert rows[2016]["delisted"] == 4
