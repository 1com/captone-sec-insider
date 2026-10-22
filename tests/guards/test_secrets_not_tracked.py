import subprocess

from conftest import REPO


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def test_env_is_ignored_and_untracked():
    assert _git("check-ignore", "-q", ".env").returncode == 0
    assert _git("ls-files", ".env").stdout.strip() == ""


def test_data_is_ignored():
    assert _git("check-ignore", "-q", "data/raw/x").returncode == 0
