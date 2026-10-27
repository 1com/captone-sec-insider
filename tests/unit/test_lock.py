"""The prereg-v1 guard (feature 006 research R1; constitution III)."""

import subprocess

import pytest

from sentinel import lock


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
                   cwd=repo, check=True, capture_output=True)  # fmt: skip


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "config").mkdir()
    params = tmp_path / "config" / "params.yaml"
    params.write_text("version: 1\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "plan")
    return tmp_path, params


def test_no_tag_is_refused(repo):
    root, params = repo
    assert "not found" in lock.problem(root, params)
    with pytest.raises(lock.NotLocked):
        lock.require(root, params)


def test_the_tagged_parameter_file_passes(repo):
    root, params = repo
    git(root, "tag", lock.TAG)
    assert lock.problem(root, params) is None
    lock.require(root, params)


def test_a_parameter_change_after_the_tag_is_refused(repo):
    root, params = repo
    git(root, "tag", lock.TAG)
    params.write_text("version: 2\n")
    assert "differs" in lock.problem(root, params)


def test_a_committed_change_after_the_tag_is_refused_too(repo):
    root, params = repo
    git(root, "tag", lock.TAG)
    params.write_text("version: 2\n")
    git(root, "commit", "-q", "-am", "change")
    assert "differs" in lock.problem(root, params)
