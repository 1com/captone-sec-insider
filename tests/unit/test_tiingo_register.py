"""The Tiingo deletion register: completeness, status and deletion (T013, W12, SC-007)."""

from datetime import date

import pytest
from conftest import PAID_DAY, issuer, store_tiingo, store_yahoo, universe_tables, weekdays

from sentinel import warehouse
from sentinel.core import prices, tiingo_register
from sentinel.ingest import manifest

DAYS = weekdays(date(2012, 1, 3), 6)


@pytest.fixture
def paid(params):
    params["ops"]["tiingo_paid_until"] = date(2026, 11, 28)
    return params


@pytest.fixture
def built(tmp_data, paid):
    """A warehouse with one Yahoo and one Tiingo issuer, built through the real steps."""
    con = warehouse.connect(tmp_data)
    universe_tables(con)
    issuer(con, "1", "AAA", "yahoo", "Aaa Inc")
    issuer(con, "2", "XYZ", "tiingo", "Xyz Corp", valid=(date(2010, 2, 1), date(2012, 1, 5)))
    store_yahoo(tmp_data, paid, {"SPY": [{"session": d, "close": 100.0} for d in DAYS],
                                 "AAA": [{"session": d, "close": 5.0} for d in DAYS]})  # fmt: skip
    store_tiingo(
        tmp_data, paid, [("XYZQ", "PINK", "Stock", "USD", "2009-01-02", "2012-01-10")],
        {"XYZQ": [{"session": d, "close": 0.5} for d in DAYS]},
        {"XYZQ": {"ticker": "xyzq", "name": "Xyz Corp", "startDate": "2009-01-02"}},
    )  # fmt: skip
    prices.build(con, tmp_data, paid, today=PAID_DAY)
    con.close()
    return tmp_data


def _rows(paths):
    con = warehouse.connect(paths, read_only=True)
    try:
        return tiingo_register.registered_rows(con), tiingo_register.unregistered_tables(con)
    finally:
        con.close()


def test_every_table_with_price_source_is_registered(built):
    _, unregistered = _rows(built)
    assert unregistered == []


def test_status_counts_registered_files_and_rows(built, paid):
    con = warehouse.connect(built, read_only=True)
    st = tiingo_register.status(con, built, paid, PAID_DAY)
    con.close()
    assert st.window_open and st.files == 3  # list, meta, prices
    assert st.rows["stg.price_tiingo"] == len(DAYS)
    assert st.rows["core.price_daily"] == len(DAYS)  # issuer 2's rows only
    assert st.problems == []


def test_status_flags_tiingo_data_outside_the_window(built, paid):
    con = warehouse.connect(built, read_only=True)
    st = tiingo_register.status(con, built, paid, date(2026, 12, 1))
    con.close()
    assert "Tiingo data is stored outside the paid window" in st.problems


def test_status_flags_stray_tiingo_files(built, paid):
    (built.data_raw.parent / "tiingo_copy.csv").write_text("x")
    st = tiingo_register.status(None, built, paid, PAID_DAY)
    assert any("tiingo_copy.csv" in p for p in st.problems)


def test_a_dry_run_deletes_nothing(built, paid):
    report = tiingo_register.delete(built, paid, yes=False, today=PAID_DAY)
    assert not report.deleted and report.files == 3
    assert _rows(built)[0]["core.price_daily"] == len(DAYS)
    assert (built.tiingo / "prices" / "XYZQ.csv.gz").exists()


def test_deletion_removes_rows_tables_and_files_and_keeps_the_rest(built, paid):
    report = tiingo_register.delete(built, paid, yes=True, today=PAID_DAY)
    assert report.deleted and "rows of core.price_daily" in report.log_line
    rows, _ = _rows(built)
    assert "stg.price_tiingo" not in rows and "core.tiingo_listing" not in rows  # dropped
    assert rows["core.price_daily"] == 0 and rows["core.price_series"] == 0
    con = warehouse.connect(built, read_only=True)
    kept = con.execute("select count(*) from core.price_daily where issuer_cik = '1'").fetchone()
    con.close()
    assert kept == (len(DAYS),)  # Yahoo rows survive
    assert not built.tiingo.exists()
    deleted = [e for e in manifest.read_all(built.manifest) if e.role == "deleted"]
    assert {e.key for e in deleted} == {"supported_tickers", "meta/XYZQ", "prices/XYZQ"}
    assert not list(built.warehouse.parent.glob("*.rewrite.duckdb"))
    after = tiingo_register.status(None, built, paid, date(2026, 12, 1))
    assert after.files == 0 and after.problems == []


def test_the_ml_dataset_copies_are_registered_files(built, paid):
    """Feature 006: the dataset's Parquet copies hold Tiingo-derived values (labels, features)."""
    copy = built.data_raw.parent / "ml" / "dataset-abc.parquet"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b"x")
    assert tiingo_register.status(None, built, paid, PAID_DAY).files == 4
    tiingo_register.delete(built, paid, yes=True, today=PAID_DAY)
    assert not copy.exists()
