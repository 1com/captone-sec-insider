from datetime import date

import pytest
from typer.testing import CliRunner

from sentinel import __version__, config, raw
from sentinel.cli import app


def test_version_command_prints_the_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0 and result.stdout.strip() == __version__


@pytest.fixture
def fake_sources(monkeypatch, tmp_data):
    """Two stand-in sources: `good` stores a file, `bad` fails; `nokey` lacks its `.env` key."""
    seen = {}

    def good(p, today, echo=print, con=None, **options):
        seen["good"] = options
        report = raw.FetchReport("yahoo")
        report.requests += 1
        report.stored(2_000_000)
        return report

    def bad(p, today, echo=print, con=None, **options):
        raise RuntimeError("provider down")

    def nokey(p, today, echo=print, con=None, **options):
        raise config.ConfigError("TIINGO_API missing in .env")

    registry = {"yahoo": good, "fred": bad, "tiingo": nokey}
    monkeypatch.setattr(raw, "fetchers", lambda: registry)
    monkeypatch.setattr(config, "paths", lambda: tmp_data)
    return seen


def test_fetch_reports_each_source_and_its_exit_code(fake_sources):
    runner = CliRunner()
    ok = runner.invoke(app, ["fetch", "yahoo", "--from", "2026-10-01", "--full-missing"])
    assert ok.exit_code == 0 and "yahoo: fetched; 1 files (2.0 MB)" in ok.stdout
    assert fake_sources["good"] == {"from_day": date(2026, 10, 1), "full_missing": True}
    assert runner.invoke(app, ["fetch", "nosuch"]).exit_code == 2
    assert runner.invoke(app, ["fetch", "yahoo", "--from", "1 Oct"]).exit_code == 2
    assert runner.invoke(app, ["fetch", "tiingo"]).exit_code == 3


def test_fetch_all_runs_every_source_and_one_failure_does_not_stop_the_others(fake_sources):
    result = CliRunner().invoke(app, ["fetch", "all"])
    assert result.exit_code == 1
    assert "yahoo: fetched" in result.stdout
    assert "fred: failed" in result.stdout and "provider down" in result.stdout
    assert "tiingo: failed" in result.stdout  # a missing key fails that source only
