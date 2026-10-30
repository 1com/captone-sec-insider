"""`sentinel status` (US5): the recent runs, each dataset's latest date, the coverage summary and
the schedule, from synthetic `ops` tables and a synthetic serving copy; it never takes the lock."""

import os
from datetime import date

import duckdb

from sentinel import db
from sentinel.update import record, status


def test_status_shows_runs_freshness_coverage_and_the_schedule_without_the_lock(tmp_data):
    con = db.connect(tmp_data)
    record.create(con)
    con.execute(
        "insert into ops.update_run values "
        "('r1', 'scheduled', '2026-10-28 23:00', '2026-10-28 23:42', 'complete', 1, 'l'), "
        "('r2', 'scheduled', '2026-10-29 23:00', '2026-10-29 23:10', 'partial', 1, 'l')"
    )
    con.execute(
        "insert into ops.update_source values "
        "('r2', 'fred', 'failed', 3, 0, 0, null, 'HTTP 500 after 5 attempts'), "
        "('r2', 'yahoo', 'fetched', 40, 37, 5000000, '2026-10-29', null)"
    )
    con.execute("create table core.price_coverage as select * from (values "
                "('1', 'yahoo', 'priced', false), ('2', 'yahoo', 'priced', false), "
                "('3', 'tiingo', 'priced', true), ('4', 'none', 'no data in any source', false)"
                ") t(cik, source, reason, tiingo_only)")  # fmt: skip
    con.close()
    with duckdb.connect(str(tmp_data.serving_db)) as serving:
        serving.execute("create schema app")
        serving.execute("create table app.freshness as select * from (values "
                        "('insider_filings', date '2026-10-29'), ('prices', date '2026-10-29')"
                        ") t(dataset, latest_date)")  # fmt: skip
    tmp_data.update_lock.parent.mkdir(parents=True, exist_ok=True)
    tmp_data.update_lock.write_text(f"{os.getpid()}\n")  # a live update's lock: left alone
    out = status.lines(tmp_data, runs=5, show=lambda p: {"Next Run Time": "30/10/2026 23:00:00"})
    text = "\n".join(out)
    assert out.index("last 5 runs:") < out.index("data as of:")
    assert "2026-10-29 23:00  scheduled  partial      10 min" in text
    assert "      fred failed: HTTP 500 after 5 attempts" in text
    assert "2026-10-28 23:00  scheduled  complete     42 min" in text
    assert (
        "  yahoo   priced" in text and "Tiingo only (stop updating when the plan ends): 1" in text
    )
    assert f"  {'prices':<24} {date(2026, 10, 29)}" in text
    assert out[-1] == "schedule: next run time 30/10/2026 23:00:00"
    assert tmp_data.update_lock.read_text() == f"{os.getpid()}\n"


def test_status_before_any_run(tmp_data):
    db.connect(tmp_data).close()
    out = status.lines(tmp_data, show=lambda p: None)
    assert out == ["runs: none yet", "data as of: nothing published yet",
                   "schedule: not installed"]  # fmt: skip
