"""The daily dilution forecasts (009, 026 FR-005, T018, V2-72) on a small synthetic panel: the
approved frozen model scores the companies still trading, with every reason, never a file from
`data/models/`; the same day scored again is replaced, not duplicated; and the live outcomes of
closed windows (`score.outcome`)."""

import json
from datetime import date
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pytest

from sentinel.models import dilution
from sentinel.scoring import daily, outcomes, schema


@pytest.fixture(autouse=True)
def small_grid(monkeypatch):
    monkeypatch.setattr(dilution, "GRID", [{"num_leaves": 7, "min_child_samples": 20}])
    monkeypatch.setattr(dilution, "TREES", [20, 40])


def _raw(companies: int = 60, seed: int = 0) -> pd.DataFrame:
    """Month-end rows 2016-2021; an offering and a small market value raise the chance."""
    rng = np.random.default_rng(seed)
    as_of = pd.date_range("2016-01-31", "2021-12-31", freq="ME")
    f = pd.DataFrame([(f"{c:04d}", d) for c in range(companies) for d in as_of],
                     columns=["cik", "as_of"])  # fmt: skip
    n = len(f)
    f["n_offering_12m"] = rng.poisson(0.3, n).astype(float)
    f["log_market_cap"] = rng.normal(20, 2, n)
    f.loc[f.index[::7], "log_market_cap"] = np.nan  # a missing input
    odds = -3 + 1.5 * (f["n_offering_12m"] > 0) - 0.3 * (f["log_market_cap"].fillna(20) - 20)
    f["dilution"] = (rng.random(n) < 1 / (1 + np.exp(-odds))).astype(float)
    f["window_end"] = f["as_of"] + pd.Timedelta(days=182)
    f["eligible_dilution"] = True
    return f


@pytest.fixture
def frozen() -> dict:
    """The approved model as `holdout.frozen_models` gives it: the model and its MLflow run."""
    none = pd.DataFrame({"cik": pd.Series(dtype=str), "as_of": pd.Series(dtype="datetime64[ns]")})
    model = dilution.fit(dilution.learnable(_raw(), none), year=2021)
    run = SimpleNamespace(info=SimpleNamespace(run_id="r1"), data=SimpleNamespace(tags={}))
    return {"model": model, "run": run}


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    """`feature.snapshot`: every company's month-end rows, the newest flagged `latest` (30 Dec
    2021); five of them outside the question; one company stopped trading in 2015."""
    rows = _raw().drop(columns=["dilution", "window_end"])
    rows["latest"] = rows["as_of"] == rows["as_of"].max()
    rows["coverage"] = "full"
    rows.loc[rows["latest"] & rows["cik"].isin(["0000", "0001", "0002", "0003", "0004"]),
             "eligible_dilution"] = False  # fmt: skip
    gone = rows[rows["latest"]].head(1).assign(cik="9999", as_of=pd.Timestamp("2015-06-30"))
    rows = pd.concat([rows, gone], ignore_index=True)
    c = duckdb.connect(":memory:")
    c.execute("create schema feature")
    c.register("_rows", rows)
    c.execute("create table feature.snapshot as select * exclude (as_of), as_of::date as as_of "
              "from _rows")  # fmt: skip
    c.unregister("_rows")
    return c


def test_schema_creation():
    c = duckdb.connect(":memory:")
    schema.create_tables(c)
    tables = {r[0] for r in c.execute("select table_name from duckdb_tables()").fetchall()}
    assert {"daily", "outcome", "registry"} <= tables


def test_the_companies_still_trading_get_the_approved_models_forecast_with_every_reason(
    con, frozen, tmp_data
):
    counts = daily.score_snapshot(con, tmp_data, frozen=frozen)
    assert counts == {"dilution": 55}  # 60 still trading, 5 outside the question; 9999 gone
    got = con.execute("select * from score.daily order by cik").df()
    assert set(got["model_version"]) == {"lightgbm-r1"} and set(got["question"]) == {"dilution"}
    assert set(got["as_of"].astype(str)) == {"2021-12-31"} and "9999" not in set(got["cik"])
    model = frozen["model"]
    rows = daily.current_rows(con)
    want = dilution.predict(model, rows).set_index("cik").loc[got["cik"]]
    assert got["forecast_val"].tolist() == want["dilution_prob"].tolist()
    assert got["band"].tolist() == want["dilution_band"].astype(int).tolist()
    extra = [json.loads(e) for e in got["extra_json"]]
    assert [e["band_name"] for e in extra] == want["dilution_band_name"].tolist()
    names = model.trees.features
    by_cik = rows.set_index("cik")
    for cik, e in zip(got["cik"], extra, strict=True):
        assert sorted(f for f, _, _ in e["factors"]) == sorted(names)
        effects = [abs(x) for _, _, x in e["factors"]]
        assert effects == sorted(effects, reverse=True)  # the largest contribution first
        for f, value, _ in e["factors"]:  # each input's own value; a missing one is None
            v = by_cik.loc[cik, f]
            assert value is None if pd.isna(v) else value == v
    # the contributions add up to the trees' log-odds, less one average shared by every company
    boost = model.trees.estimator
    x = rows.set_index("cik").loc[got["cik"], names].astype(float)
    log_odds = boost.model_.booster_.predict(x, raw_score=True, num_iteration=boost.trees_)
    total = np.array([sum(c for _, _, c in e["factors"]) for e in extra])
    assert np.ptp(log_odds - total) < 1e-9
    registry = con.execute("select question, model_version, status, features_count, "
                           "training_end from model.registry").fetchall()  # fmt: skip
    assert registry == [("dilution", "lightgbm-r1", "approved", 2,
                         date.fromisoformat(model.trained_through))]  # fmt: skip
    # the same day again: replaced, never duplicated
    assert daily.score_snapshot(con, tmp_data, frozen=frozen) == counts
    assert con.execute("select count(*) from score.daily").fetchone()[0] == 55
    assert con.execute("select count(*) from model.registry").fetchone()[0] == 1


def test_the_model_comes_from_mlflow_never_from_data_models(con, frozen, tmp_data, monkeypatch):
    from sentinel import holdout

    tmp_data.models.mkdir(parents=True, exist_ok=True)
    (tmp_data.models / "dilution.joblib").write_bytes(b"an unapproved model of 2 Nov")
    asked = []

    def frozen_models(p, questions):
        asked.append(questions)
        return {"dilution": frozen}

    monkeypatch.setattr(holdout, "frozen_models", frozen_models)
    assert daily.score_snapshot(con, tmp_data) == {"dilution": 55}
    assert asked == [("dilution",)]

    def refused(p, questions):
        raise holdout.Refused("no approved frozen model for dilution from commit abc1234 (V2-59)")

    monkeypatch.setattr(holdout, "frozen_models", refused)
    con.execute("delete from score.daily")
    with pytest.raises(holdout.Refused, match="no approved frozen model"):
        daily.score_snapshot(con, tmp_data)
    assert con.execute("select count(*) from score.daily").fetchone()[0] == 0


@pytest.fixture
def labels_con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    schema.create_tables(c)
    c.execute("create schema label")
    c.execute("create table label.volatility (cik varchar, as_of date, vol_63_future double, "
              "window_end date)")  # fmt: skip
    c.execute("create table label.dilution (cik varchar, as_of date, dilution integer, "
              "window_end date)")  # fmt: skip
    c.execute("create table label.results_move (cik varchar, as_of date, move double, "
              "close_after date)")  # fmt: skip
    return c


def test_outcome_tracking(labels_con):
    mock_db_con = labels_con
    # Insert prior daily scores
    past_date = date(2022, 5, 1)
    extra_vol = '{"vol_low_80": 0.20, "vol_high_80": 0.32}'
    extra_dil = '{"band_name": "4 · Elevated risk"}'
    extra_res = '{"p_move_5": 0.7}'
    mock_db_con.execute(f"""
        insert into score.daily values
        ('0000000001', date '{past_date}', 'volatility', 'lgbm_v1', 0.25, 2, 'full',
         '{extra_vol}', timestamp '2022-05-01 16:00:00'),
        ('0000000001', date '{past_date}', 'dilution', 'lgbm_v1', 0.15, 4, 'full',
         '{extra_dil}', timestamp '2022-05-01 16:00:00'),
        ('0000000001', date '{past_date}', 'results_move', 'lgbm_v1', 0.35, 3, 'full',
         '{extra_res}', timestamp '2022-05-01 16:00:00')
    """)

    # Insert matching realized outcomes in labels
    mock_db_con.execute(f"""
        insert into label.volatility values
        ('0000000001', date '{past_date}', 0.265, date '2022-08-01')
    """)
    mock_db_con.execute(f"""
        insert into label.dilution values
        ('0000000001', date '{past_date}', 1, date '2022-11-01')
    """)
    mock_db_con.execute(f"""
        insert into label.results_move values
        ('0000000001', date '{past_date}', 0.12, date '2022-05-03')
    """)

    # Evaluate outcomes
    counts = outcomes.evaluate_outcomes(mock_db_con)
    assert counts["volatility"] == 1
    assert counts["dilution"] == 1
    assert counts["results_move"] == 1

    outcomes_df = mock_db_con.execute("select * from score.outcome order by question").df()
    assert len(outcomes_df) == 3

    # Check volatility outcome: 0.265 is between 0.20 and 0.32 -> is_hit is True
    vol_row = outcomes_df[outcomes_df["question"] == "volatility"].iloc[0]
    assert vol_row["is_hit"] is True or vol_row["is_hit"] == 1
    assert np.isclose(vol_row["error"], 0.25 - 0.265)

    # Check dilution outcome: forecast 0.15 (>= 0.10) and actual dilution == 1 -> is_hit is True
    dil_row = outcomes_df[outcomes_df["question"] == "dilution"].iloc[0]
    assert dil_row["is_hit"] is True or dil_row["is_hit"] == 1

    # Check results_move outcome: a 35% chance of a move above 10%, and the move was 12%: the
    # event happened (actual 1), so it counts in its band's real rate (D47)
    res_row = outcomes_df[outcomes_df["question"] == "results_move"].iloc[0]
    assert res_row["actual_val"] == 1.0 and np.isclose(res_row["error"], 0.35 - 1.0)
    assert res_row["is_hit"] is True or res_row["is_hit"] == 1
