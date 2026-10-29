"""Layer 6: `sentinel publish` and `sentinel export` on the synthetic market."""

import duckdb
import pandas as pd
import pytest
from conftest import build_world

from sentinel import build, db
from sentinel.labels import lock
from sentinel.serving import export, publish

QUIET = {"echo": lambda s: None}


@pytest.fixture
def built(tmp_data, monkeypatch):
    monkeypatch.setattr(lock, "require", lambda p: None)
    with db.connect(tmp_data) as con:
        build_world(con)
        build.run(con, tmp_data, "features", **QUIET)
        build.run(con, tmp_data, "labels", **QUIET)
    return tmp_data


def test_publish_writes_every_app_table_read_only_for_the_product(built):
    counts = publish.publish(built, **QUIET)
    assert set(counts) == set(publish.TABLES)
    with duckdb.connect(str(built.serving_db), read_only=True) as con:
        stock = con.execute("select cik, ticker, coverage, has_prices from app.stock "
                            "order by cik").fetchall()  # fmt: skip
        assert stock == [("1", "AAA", "full", True), ("2", "BBB", "foreign", True)]
        card = con.execute("select as_of, next_results_estimate from app.company_card "
                           "where cik = '1'").fetchone()  # fmt: skip
        assert card[0] == pd.Timestamp("2021-12-31").date() and card[1] is not None
        feed = con.execute("select kind, ticker from app.insider_feed").fetchall()
        assert feed == [("officer_director_buy", "AAA")]
        url = con.execute("select url from app.filings where accession = 'q0'").fetchone()[0]
        assert url == "https://www.sec.gov/Archives/edgar/data/1/q0/q0-index.htm"
    assert not built.serving_db.with_suffix(".duckdb.tmp").exists()


def test_export_writes_the_training_sets_and_a_readme(built):
    publish.publish(built, **QUIET)
    counts = export.export(built, **QUIET)
    for name in ("ml/volatility.parquet", "ml/dilution.parquet", "ml/results_move.parquet",
                 "ml/latest.parquet", "app/stock.parquet"):  # fmt: skip
        assert counts[name] > 0 and (built.exports / name).exists()
    moves = pd.read_parquet(built.exports / "ml/results_move.parquet")
    assert {"move", "vol_63", "release_eve"} <= set(moves.columns)
    assert moves["release_eve"].all()  # features as of the close before each release
    assert "ml/volatility.parquet" in (built.exports / "README.md").read_text()


def test_freshness_gives_each_datasets_latest_date(built):
    publish.publish(built, **QUIET)
    with duckdb.connect(str(built.serving_db), read_only=True) as con:
        fresh = dict(con.execute("select dataset, latest_date from app.freshness").fetchall())
    assert fresh["prices"] == pd.Timestamp("2021-12-31").date()
    assert fresh["insider_filings"] == pd.Timestamp("2021-06-30").date()
    assert {"filings", "financial_values", "short_volume", "vix", "fred:DGS10"} <= set(fresh)
