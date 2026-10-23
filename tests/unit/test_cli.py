import re

from typer.testing import CliRunner

from sentinel import cli
from sentinel.config import Paths

COMMANDS = [
    "check",
    "explore",
    "fetch-sec",
    "verify-sec",
    "stage",
    "entities",
    "gates",
    "detect-prelim",
    "candidates-provisional",
    "symbols",
    "fetch-sec-tickers",
    "fetch-prices",
    "fetch-reference",
    "detect",
    "delistings",
    "shares-out",
    "costs",
    "prereg-status",
    "labels",
    "features",
    "serve",
    "event-study",
    "ml-dataset",
    "baselines",
    "tournament",
    "explain",
    "holdout",
    "score-live",
    "robustness",
    "report",
]
PANELS = [cli.P0, cli.P1, cli.P2, cli.P3, cli.P4]

runner = CliRunner()


def test_help_lists_every_step_and_phase():
    result = runner.invoke(cli.app, ["--help"], env={"COLUMNS": "200", "NO_COLOR": "1"})
    assert result.exit_code == 0
    listed = set(re.findall(r"│ ([a-z][a-z-]+) ", result.output))
    assert set(COMMANDS) <= listed
    for panel in PANELS:
        assert panel in result.output


def test_stub_exits_4():
    result = runner.invoke(cli.app, ["fetch-prices"])
    assert result.exit_code == cli.NOT_IMPLEMENTED
    assert "not yet implemented — plan Step 7" in result.output


def test_unknown_option_is_a_usage_error():
    assert runner.invoke(cli.app, ["fetch-sec", "--bogus"]).exit_code == cli.USAGE


def test_check_passes_and_hides_the_key(tmp_path, fake_env, monkeypatch):
    real = cli.repo_root()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "params.yaml").write_text((real / "config" / "params.yaml").read_text())
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "initialplan.md").write_text(
        (real / "docs" / "initialplan.md").read_text()
    )
    paths = Paths.from_root(tmp_path)
    monkeypatch.setattr(cli, "_paths", lambda: paths)
    monkeypatch.setattr(cli, "_data_ignored", lambda p: True)
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == cli.OK, result.output
    assert "tiingo-secret-123" not in result.output
    assert "FAIL" not in result.output
