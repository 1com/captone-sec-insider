"""The holdout test (010): the same label rule with a later end date, the guard, the check mode
that computes no answer, and a run that records once and refuses a second time."""

import dataclasses
import json
import types
from datetime import date

import duckdb
import mlflow
import numpy as np
import pandas as pd
import pytest
from mlflow.tracking import MlflowClient

from sentinel import config, holdout
from sentinel.labels import risk as labels
from sentinel.models import report


def _inputs(seed: int = 0):
    """Three companies' prices, share counts and results releases, 2019-2024."""
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2019-01-02", "2024-12-31")
    calendar = sessions.to_numpy(dtype="datetime64[ns]")
    ciks = ["0001", "0002", "0003"]
    daily = pd.concat(
        [
            pd.DataFrame(
                {
                    "cik": c,
                    "session": sessions,
                    "cum_split_after": 1.0,
                    "adj_close": 20 * np.exp(np.cumsum(rng.normal(0, 0.02, len(sessions)))),
                }
            )
            for c in ciks
        ],
        ignore_index=True,
    )
    month_ends = sessions.to_series().groupby(sessions.to_period("M")).max().to_numpy()
    rows = pd.DataFrame([(c, d) for c in ciks for d in month_ends], columns=["cik", "as_of"])
    quarters = pd.date_range("2018-12-31", "2024-12-31", freq="QE")
    shares = pd.DataFrame(
        [
            (c, q, 1e6 * 1.02**i * (1.3 if i % 7 == 3 else 1.0), q + pd.Timedelta(days=40))
            for c in ciks
            for i, q in enumerate(quarters)
        ],
        columns=["cik", "period_end", "value", "filed"],
    )
    releases = pd.DataFrame(
        [(c, q + pd.Timedelta(days=30), q + pd.Timedelta(days=29)) for c in ciks for q in quarters],
        columns=["cik", "filing_date", "report_date"],
    )
    spy = pd.DataFrame(
        {
            "session": sessions,
            "adj_close": 300 * np.exp(np.cumsum(rng.normal(0, 0.01, len(sessions)))),
        }
    )
    return daily, rows, calendar, shares, releases, spy


def test_the_labels_with_a_later_end_date_give_the_development_answers():
    rules = config.risk_params(config.paths())
    daily, rows, calendar, shares, releases, spy = _inputs()
    steps = labels.share_steps(shares)
    dev_end, later = date(2022, 12, 31), date(2024, 12, 31)
    early = labels.month_labels(daily, rows, calendar, steps, rules, dev_end)
    late = labels.month_labels(daily, rows, calendar, steps, rules, later)
    # the run labels only the rows from 2023 on: the same answers as labelling every row
    held = rows[pd.to_datetime(rows["as_of"]) >= holdout.START]
    alone = labels.month_labels(daily, held, calendar, steps, rules, later)
    with_all = late[pd.to_datetime(late["as_of"]) >= holdout.START]
    pd.testing.assert_frame_equal(alone.reset_index(drop=True), with_all.reset_index(drop=True))
    for value, end in (("vol_63_future", "vol_window_end"), ("dilution", "dilution_window_end")):
        e = early[early[end].notna()].set_index(["cik", "as_of"])[[value, end]]
        assert len(e) > 0
        pd.testing.assert_frame_equal(
            e, late.set_index(["cik", "as_of"]).loc[e.index, [value, end]]
        )
        assert late[end].notna().sum() > len(e)  # the later end date labels more rows
    gap = int(rules["labels"]["results_move"]["max_report_gap_days"])
    m_early = labels.results_moves(daily, releases, calendar, spy, dev_end, gap)
    m_late = labels.results_moves(daily, releases, calendar, spy, later, gap)
    kept = m_late[m_late["close_after"] <= dev_end].reset_index(drop=True)
    pd.testing.assert_frame_equal(m_early.reset_index(drop=True), kept)  # prev4_mean included
    assert len(m_late) > len(m_early) > 0


@pytest.fixture
def paths(tmp_path, monkeypatch):
    p = dataclasses.replace(
        config.paths(),
        exports=tmp_path / "exports",
        mlflow_db=tmp_path / "mlflow.db",
        build_db=tmp_path / "build.duckdb",
    )
    monkeypatch.setattr(holdout.lock, "problem", lambda p: None)  # the registration holds
    before = mlflow.get_tracking_uri()
    yield p
    mlflow.set_tracking_uri(before)


def test_a_clean_store_passes_the_guard(paths):
    holdout.guard(paths)


def test_a_log_entry_refuses_a_second_run(paths):
    holdout.log_path(paths).parent.mkdir(parents=True)
    holdout.log_path(paths).write_text('{"run_date": "2026-11-16"}\n')
    with pytest.raises(holdout.Refused, match="already run"):
        holdout.guard(paths)


def test_a_holdout_record_refuses_a_second_run(paths, tmp_path):
    mlflow.set_tracking_uri(f"sqlite:///{paths.mlflow_db}")
    mlflow.create_experiment(holdout.EXPERIMENT, artifact_location=(tmp_path / "art").as_uri())
    mlflow.set_experiment(holdout.EXPERIMENT)
    with mlflow.start_run(run_name="holdout-dilution"):
        pass
    with pytest.raises(holdout.Refused, match="already holds a run"):
        holdout.guard(paths)


def test_a_changed_registration_is_refused(paths, monkeypatch):
    monkeypatch.setattr(holdout.lock, "problem", lambda p: "config/risk_params.yaml differs")
    with pytest.raises(holdout.Refused, match="registration lock"):
        holdout.guard(paths)


def _fake_frozen(monkeypatch):
    run = types.SimpleNamespace(
        data=types.SimpleNamespace(tags={"levels": "a,b"}), info=types.SimpleNamespace(run_id="run")
    )
    models = {
        q: {
            "model": None,
            "run": run,
            "commit": "abc1234",
            "data_hash": "hash",
            "export_date": "2026-11-09",
        }
        for q in ("dilution", "results_move", "volatility")
    }
    monkeypatch.setattr(holdout, "frozen_models", lambda p: models)
    monkeypatch.setattr(
        holdout, "frozen_levels", lambda p, m: {q: {"levels": {}, "run": run} for q in m}
    )


def test_the_check_computes_no_answer(paths, monkeypatch):
    _fake_frozen(monkeypatch)

    def no_answers(*args, **kwargs):
        raise AssertionError("an answer was computed")

    monkeypatch.setattr(labels, "month_labels", no_answers)
    monkeypatch.setattr(labels, "results_moves", no_answers)
    with duckdb.connect(str(paths.build_db)) as con:
        con.execute("create schema feature; create schema stg_yahoo")
        con.execute(
            "create table feature.snapshot as select * from (values "
            "(DATE '2023-01-31', true, false, true, true, true), "
            "(DATE '2023-02-03', false, true, true, false, false), "
            "(DATE '2022-12-30', true, false, true, true, true)) "
            "t(as_of, month_end, release_eve, eligible, eligible_volatility, "
            "eligible_dilution)"
        )
        con.execute(
            "create table stg_yahoo.price as select 'SPY' as ticker, "
            "DATE '2026-11-13' as session, 500.0 as adj_close"
        )
    out = holdout.check(paths, echo=lambda _: None)
    assert out["counts"] == {"volatility": 1, "dilution": 1, "results_move": 1}


def test_a_run_records_once_at_the_end_and_refuses_a_second(paths, monkeypatch, tmp_path):
    _fake_frozen(monkeypatch)
    mlflow.set_tracking_uri(f"sqlite:///{paths.mlflow_db}")
    mlflow.create_experiment(holdout.EXPERIMENT, artifact_location=(tmp_path / "art").as_uri())
    with duckdb.connect(str(paths.build_db)) as con:
        con.execute("create schema feature")
        con.execute("create table feature.snapshot as select DATE '2023-01-31' as as_of")
    months = pd.DataFrame({c: [] for c in labels.MONTH_COLUMNS})
    moves = pd.DataFrame(
        {c: [] for c in ("cik", "as_of", "filing_date", "report_date", "close_after")}
    )
    monkeypatch.setattr(holdout, "answers", lambda con, rules, echo: (months, moves, "2026-11-13"))
    monkeypatch.setattr(holdout.dilution, "split_like_answers", lambda con, rows: rows.iloc[0:0])
    rows = pd.DataFrame({"as_of": pd.to_datetime(["2023-01-31", "2024-01-31"])})
    monkeypatch.setattr(holdout, "_question_rows", lambda *a: (rows, {"scored": 2}))
    calls = []

    def score(q, r, model, frozen):
        calls.append(q)
        if len(calls) == 3:  # every question is scored before anything is written
            assert (
                MlflowClient(f"sqlite:///{paths.mlflow_db}").search_runs(
                    [mlflow.get_experiment_by_name(holdout.EXPERIMENT).experiment_id]
                )
                == []
            )
            assert not holdout.log_path(paths).exists()
        measure = holdout.DECIDING[q]
        res = pd.DataFrame(
            {"level": ["baseline", "model (chosen)"], "year": ["all", "all"], measure: [0.5, 0.4]}
        )
        out = {"results": res, "bands": pd.DataFrame({"year": ["all"], "band": [1], "rows": [2]})}
        if q == "volatility":
            out["coverage"] = pd.DataFrame({"year": ["all"], "coverage": [0.8]})
        return out

    monkeypatch.setattr(holdout, "_score_question", score)
    entry = holdout.run(paths, echo=lambda _: None)
    assert set(entry["questions"]) == {"dilution", "results_move", "volatility"}
    lines = holdout.log_path(paths).read_text().strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["data_date"] == "2026-11-13"
    runs = MlflowClient(f"sqlite:///{paths.mlflow_db}").search_runs(
        [mlflow.get_experiment_by_name(holdout.EXPERIMENT).experiment_id]
    )
    assert sorted(r.data.tags["question"] for r in runs) == [
        "dilution",
        "results_move",
        "volatility",
    ]
    assert all(r.data.tags["holdout"] == "true" for r in runs)
    # the model report reads them back beside the notebooks' records (008 contract)
    for q, (name, *_) in report.QUESTIONS.items():
        mlflow.create_experiment(name, artifact_location=(tmp_path / name).as_uri())
        mlflow.set_experiment(name)
        report.record(q, {"title": q}, {"trial": False})
    _, held = report.load_records(f"sqlite:///{paths.mlflow_db}")
    assert set(held) == {"dilution", "results_move", "volatility"}
    assert held["dilution"]["tables"]["results"]["columns"] == ["level", "year", "log_loss"]
    assert held["dilution"]["tables"]["rows"] == 2
    assert held["dilution"]["tables"]["row_counts"] == {"scored": 2}
    assert (
        "coverage" in held["volatility"]["tables"] and "coverage" not in held["dilution"]["tables"]
    )
    with pytest.raises(holdout.Refused, match="already run"):
        holdout.run(paths, echo=lambda _: None)


def test_the_rows_left_out_are_counted():
    d = pd.to_datetime
    snap = pd.DataFrame(
        {
            "cik": ["1", "2", "3", "1", "2"],
            "as_of": d(["2023-01-31"] * 3 + ["2023-02-02", "2023-02-03"]),
            "month_end": [True, True, True, False, False],
            "release_eve": [False, False, False, True, True],
            "eligible": [True] * 5,
            "eligible_volatility": [True, True, False, False, False],
            "eligible_dilution": [True, True, True, False, False],
        }
    )
    months = pd.DataFrame(
        {
            "cik": ["1", "2", "3"],
            "as_of": d(["2023-01-31"] * 3),
            "vol_63_future": [0.3, 0.0, 0.5],
            "vol_window_end": d(["2023-05-03"] * 3),
            "dilution": [1.0, None, 0.0],
            "dilution_window_end": d(["2023-08-01"] * 3),
        }
    )
    moves = pd.DataFrame(
        {
            "cik": ["1"],
            "as_of": d(["2023-02-02"]),
            "filing_date": d(["2023-02-03"]),
            "report_date": d(["2023-02-03"]),
            "close_after": d(["2023-02-06"]),
            "move": [0.12],
            "prev4_mean": [0.05],
            "n_prev": [4],
        }
    )
    split_like = pd.DataFrame({"cik": ["1"], "as_of": d(["2023-01-31"])})
    rows, n = holdout._question_rows("volatility", snap, months, moves, split_like)
    assert list(rows["cik"]) == ["1"]  # the answer of 0 is left out (no logarithm)
    assert n == {
        "eligible month-ends": 2,
        "no answer (window open or data missing)": 0,
        "left out: answer of 0": 1,
        "scored": 1,
    }
    rows, n = holdout._question_rows("dilution", snap, months, moves, split_like)
    assert list(rows["cik"]) == ["3"]  # company 1's answer is split-like, company 2 has none
    assert n == {
        "eligible month-ends": 3,
        "no answer (window open or data missing)": 1,
        "left out: split-like answer": 1,
        "scored": 1,
    }
    rows, n = holdout._question_rows("results_move", snap, months, moves, split_like)
    assert list(rows["cik"]) == ["1"]
    assert n == {
        "eligible release eves": 2,
        "no move (window open or closes missing)": 1,
        "scored": 1,
    }
