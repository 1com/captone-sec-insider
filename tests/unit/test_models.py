"""Unit tests for the model commands; the approved models (005, 006, 007) have their own test
files."""


def test_cli_models_validation():
    from typer.testing import CliRunner

    from sentinel.cli import app

    runner = CliRunner()
    res_train = runner.invoke(app, ["train", "nonexistent"])
    assert res_train.exit_code == 2
    assert "unknown question 'nonexistent'" in res_train.stderr

    res_score = runner.invoke(app, ["score", "nonexistent"])
    assert res_score.exit_code == 2
    assert "unknown question 'nonexistent'" in res_score.stderr

    res_score_file = runner.invoke(
        app, ["score", "results_move", "--input", "no_such_file.parquet"]
    )
    assert res_score_file.exit_code == 1
    assert "input file does not exist" in res_score_file.stderr
