"""Layer 6: `sentinel publish` and `sentinel export` on the synthetic market."""

import duckdb
import pandas as pd
import pytest
from conftest import build_world

from sentinel import build, db
from sentinel.labels import lock
from sentinel.scoring import schema
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
    assert set(counts) == set(publish.TABLES) | {"daily_score"}
    assert counts["daily_score"] == 0  # no forecasts in this build: the table is there, empty
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


def test_publish_serves_each_companys_newest_forecast_of_an_approved_model_only(built):
    """V2-72: the unapproved models' forecasts of 2 and 4 Nov stay in the log, never served.
    V2-73: a company whose latest row has left the question (a stock that fell below $1) keeps
    no forecast of an earlier day. V2-74: nor one whose latest row has no share count (the
    answer cannot be measured, so the model was never tested on such rows)."""
    with db.connect(built) as con:
        schema.create_tables(con)
        con.execute("insert into model.registry values ('dilution', 'lightgbm-ok', 'LightGBM', "
                    "DATE '2021-06-30', 2, 'approved', TIMESTAMP '2026-11-12 10:00')")  # fmt: skip
        con.execute("update feature.snapshot set eligible_dilution = true, "
                    "shares_outstanding = 1000000 where cik = '1' and latest")  # fmt: skip
        # 4: in the question; 5: fell below $1 on its latest day; 6: in it, no share count
        for cik, inside, shares in (("4", True, "1000000"), ("5", False, "1000000"),
                                    ("6", True, "null")):  # fmt: skip
            con.execute(f"insert into feature.snapshot select * replace ('{cik}' as cik, "
                        f"{inside} as eligible_dilution, {shares} as shares_outstanding) "
                        "from feature.snapshot where cik = '1' and latest")  # fmt: skip
        con.execute("""insert into score.daily values
            ('1', DATE '2026-11-10', 'dilution', 'lightgbm-ok', 0.2, 3, 'full', '{}',
             TIMESTAMP '2026-11-10 10:30'),
            ('1', DATE '2026-11-11', 'dilution', 'lightgbm-ok', 0.3, 4, 'full', '{}',
             TIMESTAMP '2026-11-11 10:30'),
            ('1', DATE '2026-11-11', 'dilution', 'lightgbm_v1', 0.9, 5, 'full', '{}',
             TIMESTAMP '2026-11-11 10:31'),
            ('4', DATE '2026-11-03', 'dilution', 'lightgbm-ok', 0.1, 2, 'full', '{}',
             TIMESTAMP '2026-11-03 10:30'),
            ('5', DATE '2026-11-10', 'dilution', 'lightgbm-ok', 0.8, 5, 'full', '{}',
             TIMESTAMP '2026-11-10 10:30'),
            ('6', DATE '2026-11-11', 'dilution', 'lightgbm-ok', 0.79, 5, 'full', '{}',
             TIMESTAMP '2026-11-11 10:30'),
            ('3', DATE '2026-11-04', 'dilution', 'lightgbm_v1', 0.5, 5, 'full', '{}',
             TIMESTAMP '2026-11-04 10:30')""")  # 4: more than a week old; 3: unapproved only
    publish.publish(built, **QUIET)
    with duckdb.connect(str(built.serving_db), read_only=True) as con:
        served = con.execute("select cik, as_of, model_version, forecast_val, band "
                             "from app.daily_score").fetchall()  # fmt: skip
    assert served == [("1", pd.Timestamp("2026-11-11").date(), "lightgbm-ok", 0.3, 4)]


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


def test_export_replaces_only_its_own_files(built):
    publish.publish(built, **QUIET)
    export.export(built, **QUIET)
    kept = [built.exports / "reference" / "volatility.parquet",
            built.exports / "share" / "list.csv"]  # fmt: skip
    for f in kept:
        f.parent.mkdir(exist_ok=True)
        f.write_text("private")
    (built.exports / "ml" / "stale.parquet").write_text("from an older export")
    export.export(built, **QUIET)
    assert all(f.read_text() == "private" for f in kept)
    assert not (built.exports / "ml" / "stale.parquet").exists()


def test_freshness_gives_each_datasets_latest_date(built):
    publish.publish(built, **QUIET)
    with duckdb.connect(str(built.serving_db), read_only=True) as con:
        fresh = dict(con.execute("select dataset, latest_date from app.freshness").fetchall())
    assert fresh["prices"] == pd.Timestamp("2021-12-31").date()
    assert fresh["insider_filings"] == pd.Timestamp("2021-06-30").date()
    assert {"filings", "financial_values", "short_volume", "vix", "fred:DGS10"} <= set(fresh)
