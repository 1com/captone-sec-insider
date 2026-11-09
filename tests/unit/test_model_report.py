"""The model report (008) generated from synthetic records in a temporary MLflow store: its numbers
are the recorded ones, trial and older records are ignored, a missing question stops it, two runs
give identical files, and the holdout section shows 010's record unedited when it exists."""

import json
import tempfile
import time
from pathlib import Path

import mlflow
import pandas as pd
import pytest
from typer.testing import CliRunner

from sentinel import config
from sentinel.models import report

YEARS = (2019, 2020, 2021, 2022)
LEVELS = ["baseline", "rule", "model"]


def _tables(question: str, shift: float = 0.0) -> dict:
    res = pd.DataFrame([{"level": lv, "year": y, "score": 0.5 - 0.1 * i + 0.01 * (y - 2019) + shift,
                         "other": 0.25} for i, lv in enumerate(LEVELS) for y in YEARS])  # fmt: skip
    bands = pd.DataFrame([{"year": y, "band": b, "rows": 100 * b, "forecast": 0.1 * b,
                           "real": 0.1 * b + 0.01, "median_size": 0.2 * b}
                          for y in YEARS for b in range(1, 6)])  # fmt: skip
    cal = pd.DataFrame([{"year": y, "group": g, "forecast": g / 10, "real": g / 10}
                        for y in YEARS for g in range(1, 11)])  # fmt: skip
    return {"title": question, "feature": "000", "approved": "V2-00",
            "question_text": "A question?", "decisions": ["A decision."],
            "deciding": {"measure": "score", "label": "score", "lower_is_better": True},
            "levels": LEVELS, "chosen": "model", "textbook": "rule",
            "data": {"rows": 1000, "companies": 10},
            "folds": pd.DataFrame({"year": list(YEARS), "train": [500] * 4, "test": [100] * 4}),
            "results": res,
            "choice": pd.DataFrame({"level": LEVELS, "mean": [0.515, 0.415, 0.315]}),
            "bands": bands, "calibration": cal,
            "hypotheses": pd.DataFrame({"hypothesis": ["H-1"], "verdict": ["supported"]}),
            "frozen": {"level": "model", "setting": "{}"}}  # fmt: skip


def _record(question: str, shift: float, tags: dict) -> None:
    mlflow.set_experiment(report.QUESTIONS[question][0])
    report.record(question, _tables(question, shift), tags)
    time.sleep(0.01)  # distinct start times: the newest record is read


@pytest.fixture
def store(tmp_path):
    before = mlflow.get_tracking_uri()
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    mlflow.set_tracking_uri(uri)
    for q, (experiment, *_) in report.QUESTIONS.items():
        mlflow.create_experiment(experiment, artifact_location=(tmp_path / "art").as_uri())
        _record(q, 0.5, {"git_commit": "older", "trial": "False"})
        _record(q, 0.0, {"git_commit": "abc1234", "export_date": "2026-11-09",
                         "data_hash": "hash", "trial": "False"})  # fmt: skip
        _record(q, 9.0, {"git_commit": "trial", "trial": "True"})
    yield uri
    mlflow.set_tracking_uri(before)


def test_the_numbers_are_the_newest_records_and_trials_are_ignored(store, tmp_path):
    out = tmp_path / "report"
    path = report.generate_report(config.paths(), tracking_uri=store, out=out, echo=lambda _: None)
    card = json.loads((out / "model_card.json").read_text())
    assert set(card) == set(report.QUESTIONS)
    for q in report.QUESTIONS:
        assert card[q]["source"]["git_commit"] == "abc1234"
        assert card[q]["chosen"] == "model"
        assert card[q]["test_years"]["2019"]["model"] == pytest.approx(0.3)
        assert card[q]["test_years"]["2022"]["baseline"] == pytest.approx(0.53)
        assert card[q]["holdout"] is None
    text = path.read_text()
    assert "| model | 0.3000 | 0.3100 | 0.3200 | 0.3300 | 0.3150 |" in text  # level x year, mean
    assert "older" not in text and "| trial" not in text
    assert text.count("Not run yet") == 3
    assert (out / "figures" / "dilution_results.png").exists()


def test_bands_pool_counts_and_shares_but_not_medians(store, tmp_path):
    out = tmp_path / "report"
    report.generate_report(config.paths(), tracking_uri=store, out=out, echo=lambda _: None)
    pooled = json.loads((out / "model_card.json").read_text())["dilution"]["bands_pooled"]
    frame = pd.DataFrame(pooled["data"], columns=pooled["columns"])
    assert list(frame.columns) == ["band", "rows", "forecast", "real"]
    assert frame.loc[frame.band == 2, "rows"].item() == 800
    assert frame.loc[frame.band == 2, "real"].item() == pytest.approx(0.21)


def test_two_runs_give_identical_files(store, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for out in (a, b):
        report.generate_report(config.paths(), tracking_uri=store, out=out, echo=lambda _: None)
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files and files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    for f in files:
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_a_missing_question_stops_the_command_and_writes_nothing(tmp_path):
    before = mlflow.get_tracking_uri()
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    mlflow.set_tracking_uri(uri)
    try:
        experiment = report.QUESTIONS["dilution"][0]
        mlflow.create_experiment(experiment, artifact_location=(tmp_path / "art").as_uri())
        _record("dilution", 0.0, {"git_commit": "abc1234"})
        out = tmp_path / "report"
        with pytest.raises(report.MissingRecords, match="results_move.*volatility"):
            report.generate_report(config.paths(), tracking_uri=uri, out=out)
        assert not out.exists()
    finally:
        mlflow.set_tracking_uri(before)


def test_the_holdout_record_is_shown_unedited(store, tmp_path):
    mlflow.create_experiment(report.HOLDOUT_EXPERIMENT,
                             artifact_location=(tmp_path / "hold").as_uri())  # fmt: skip
    mlflow.set_experiment(report.HOLDOUT_EXPERIMENT)
    holdout = {"question": "dilution", "date": "2026-11-16", "rows": 12345,
               "results": {"columns": ["level", "score"], "data": [["model", 0.4321]]}}  # fmt: skip
    with tempfile.TemporaryDirectory() as tmp, mlflow.start_run(run_name="holdout"):
        mlflow.set_tags({"holdout": "true", "question": "dilution"})
        path = Path(tmp) / "holdout.json"
        path.write_text(json.dumps(holdout))
        mlflow.log_artifact(str(path))
    out = tmp_path / "report"
    text = report.generate_report(config.paths(), tracking_uri=store, out=out,
                                  echo=lambda _: None).read_text()  # fmt: skip
    assert "| model | 0.4321 |" in text and "2026-11-16" in text
    assert text.count("Not run yet") == 2
    card = json.loads((out / "model_card.json").read_text())
    assert card["dilution"]["holdout"]["rows"] == 12345 and card["volatility"]["holdout"] is None


def test_a_named_index_is_kept_and_row_numbers_are_dropped():
    years = pd.DataFrame({"x": [1.0, 2.0]}, index=pd.RangeIndex(2019, 2021, name="year"))
    assert report._value(years) == {"columns": ["year", "x"], "data": [[2019, 1.0], [2020, 2.0]]}
    stacked = pd.concat([pd.DataFrame({"x": [1.0]}), pd.DataFrame({"x": [2.0]})])  # index 0, 0
    assert report._value(stacked) == {"columns": ["x"], "data": [[1.0], [2.0]]}


def test_the_command_reports_missing_records(monkeypatch):
    def missing(*args, **kwargs):
        raise report.MissingRecords("no report record for dilution")

    monkeypatch.setattr(report, "generate_report", missing)
    from sentinel.cli import app

    result = CliRunner().invoke(app, ["report"])
    assert result.exit_code == 1 and "no report record for dilution" in result.stderr
