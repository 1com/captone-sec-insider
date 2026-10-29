from typer.testing import CliRunner

from sentinel import __version__
from sentinel.cli import app


def test_version_command_prints_the_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0 and result.stdout.strip() == __version__
