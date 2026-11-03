"""Unit test for automated model report generation (Feature 008)."""

from typer.testing import CliRunner

from sentinel import config
from sentinel.cli import app


def test_sentinel_report_command_generates_markdown_and_figures():
    runner = CliRunner()
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0
    assert "Report saved to" in result.stdout

    p = config.paths()
    report_file = p.root / "docs" / "model_report.md"
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "EDGAR-SENTINEL v2: Formal Model Evaluation Report" in content
    assert "Dilution (007)" in content
    assert "Volatility (005)" in content
    assert "Results-Day Move (006)" in content

    fig_dir = p.root / "docs" / "figures"
    assert (fig_dir / "dilution_calibration.png").exists()
    assert (fig_dir / "volatility_intervals.png").exists()
    assert (fig_dir / "feature_importance.png").exists()
