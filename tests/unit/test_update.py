"""The daily update (US3): equal to a full rebuild, unchanged by a rerun, catching up missed days,
partial when a source fails, one at a time, refusing a nearly full disk. A stand-in Yahoo source
writes real window files; staging is the real Yahoo step; one small step stands for the layers
above (no network)."""

import io
import os
from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest

from sentinel import build, db, raw
from sentinel.raw import FetchReport
from sentinel.raw.manifest import Manifest, store_bytes
from sentinel.staging import prices
from sentinel.update import run as updater
from sentinel.update import verify as verifier

DAYS = [date(2026, 10, 26) + timedelta(days=i) for i in range(5)]  # Monday to Friday
QUIET = lambda s: None  # noqa: E731


def _window(p, day: date, sessions: list[date]) -> None:
    """A Yahoo window file of ticker AAA covering `sessions`, fetched on `day`."""
    n = len(sessions)
    frame = pd.DataFrame({
        "ticker": ["AAA"] * n, "Date": pd.to_datetime(sessions),
        **{c: [10.0 + DAYS.index(s) for s in sessions] for c in ("Open", "High", "Low", "Close",
                                                                "Adj Close")},
        "Volume": [100.0] * n, "Dividends": [0.0] * n, "Stock Splits": [0.0] * n})  # fmt: skip
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    store_bytes(p, Manifest(p.manifest), "yahoo", f"yahoo/daily/{day}/batch-000.parquet",
                f"daily/{day}/000", buf.getvalue(), "stand-in")  # fmt: skip


def _twice(con, p, echo) -> dict:
    """The stand-in for the layers above staging: a table built from staged prices."""
    con.execute("create or replace table core.test_close as "
                "select ticker, session, close * 2 as twice from stg_yahoo.price")  # fmt: skip
    return {"rows": db.count(con, "core.test_close")}


def _publish(p, echo=print) -> dict:
    with duckdb.connect(str(p.serving_db)) as con:
        con.execute(f"attach '{p.build_db.as_posix()}' as b (read_only)")
        con.execute("create schema if not exists app")
        con.execute("create or replace table app.price_daily as "
                    "select ticker as cik, session, twice from b.core.test_close")  # fmt: skip
    return {"price_daily": 1}


def _min_free(p, gb: int) -> None:
    text = p.sources_file.read_text()
    p.sources_file.write_text(text.replace("min_free_gb: 20", f"min_free_gb: {gb}")
                              .replace("min_free_gb: 0", f"min_free_gb: {gb}"))  # fmt: skip


@pytest.fixture
def world(tmp_data, monkeypatch):
    calls: list[list[date]] = []

    def yahoo(p, today, echo=print, con=None, **_):
        """Every weekday after the last window up to today: missed days included."""
        report = FetchReport("yahoo")
        keys = [e.key for e in Manifest(p.manifest).originals("yahoo")]
        last = max((date.fromisoformat(k.split("/")[1]) for k in keys), default=date(2026, 10, 25))
        sessions = [d for d in DAYS if last < d <= today]
        calls.append(sessions)
        if sessions:
            _window(p, today, sessions)
            report.stored(1)
            report.latest_date = sessions[-1]
        return report

    monkeypatch.setattr(raw, "fetchers", lambda: {"yahoo": yahoo})
    _min_free(tmp_data, 0)  # the temporary folder's disk is small; one test checks the floor
    monkeypatch.setitem(build.LAYERS, "staging", {"yahoo": prices.stage_yahoo})
    monkeypatch.setitem(build.LAYERS, "test", {"twice": _twice})
    options = {"layers": ("test",), "publish": _publish, "export": lambda p, echo=print: {},
               "echo": QUIET}  # fmt: skip
    return tmp_data, calls, options


def _scalar(p, sql: str):
    with duckdb.connect(str(p.build_db), read_only=True) as con:
        return con.execute(sql).fetchone()[0]


def test_an_update_equals_a_full_rebuild_and_a_rerun_changes_nothing(world):
    p, _, options = world
    first = updater.update(p, today=DAYS[2], **options)
    assert first["status"] == "complete"
    assert first["app"]["price_daily"] == (0, 3, 3, 0, 0)  # three days added
    again = updater.update(p, today=DAYS[2], **options)
    assert again["status"] == "nothing_new"
    assert again["app"]["price_daily"][2:] == (0, 0, 0)  # none added, changed or removed
    assert verifier.verify(p, layers=("staging", "test"), echo=QUIET) == []


def test_missed_days_are_caught_up_in_order(world):
    p, calls, options = world
    updater.update(p, today=DAYS[0], **options)
    updater.update(p, today=DAYS[3], **options)  # Tuesday and Wednesday were missed
    assert calls[-1] == DAYS[1:4]
    assert _scalar(p, "select list(session order by session) from stg_yahoo.price") == DAYS[:4]


def test_a_failing_source_leaves_the_others_and_the_run_is_partial(world, monkeypatch):
    p, _, options = world
    yahoo = raw.fetchers()["yahoo"]

    def down(p, today, echo=print, con=None, **_):
        raise RuntimeError("provider down")

    monkeypatch.setattr(raw, "fetchers", lambda: {"yahoo": yahoo, "fred": down})
    result = updater.update(p, today=DAYS[1], **options)
    assert result["status"] == "partial"
    assert result["sources"] == {"yahoo": "fetched", "fred": "failed"}
    assert _scalar(p, "select count(*) from core.test_close") == 2  # Yahoo's days still built
    assert _scalar(p, "select status from ops.update_run") == "partial"
    assert "provider down" in _scalar(p, "select error from ops.update_source "
                                         "where source = 'fred'")  # fmt: skip


def test_one_update_at_a_time_and_never_on_a_nearly_full_disk(world, monkeypatch):
    p, calls, options = world
    p.update_lock.parent.mkdir(parents=True, exist_ok=True)
    p.update_lock.write_text(f"{os.getpid()}\n")  # this process: alive
    with pytest.raises(updater.UpdateLocked, match=str(os.getpid())):
        updater.update(p, today=DAYS[0], **options)
    p.update_lock.write_text("999999\n")  # a process that is gone: its lock is replaced
    assert updater.update(p, today=DAYS[0], **options)["status"] == "complete"
    assert not p.update_lock.exists()
    _min_free(p, 20)
    full = type("Usage", (), {"free": 1e9})()  # 1 GB free
    monkeypatch.setattr(updater.shutil, "disk_usage", lambda path: full)
    calls.clear()
    with pytest.raises(updater.DiskFull):
        updater.update(p, today=DAYS[1], **options)
    assert calls == []  # stopped before fetching


def test_an_update_without_fetching_records_its_run(world):
    p, calls, options = world
    updater.update(p, today=DAYS[1], **options)
    result = updater.update(p, today=DAYS[1], fetch=False, **options)
    assert result["status"] == "nothing_new" and calls == [DAYS[:2]]
    assert _scalar(p, "select count(*) from ops.update_run where finished_at is not null") == 2
