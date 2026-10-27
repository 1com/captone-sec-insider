"""The pre-registration lock (constitution III; feature 006 research R1).

No post-event return may be computed before the plan and `config/params.yaml` are tagged
`prereg-v1`. The steps that compute returns (labels, features with F10, the ML dataset) call
`require` first: it passes only when the tag exists and the parameter file is byte-identical to
its version at the tag. The check is local (no network), so the offline rebuild can run it.
"""

import subprocess
from pathlib import Path

TAG = "prereg-v1"


class NotLocked(Exception):
    """The pre-registration is not locked, or the parameter file changed since the lock."""


def problem(root: Path, params_file: Path) -> str | None:
    """None when `prereg-v1` exists and `params_file` equals its version at the tag; else why."""

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=root, capture_output=True)

    if git("rev-parse", "-q", "--verify", f"refs/tags/{TAG}").returncode != 0:
        return f"tag {TAG} not found: lock the pre-registration first (planning tasks L.1–L.3)"
    relative = params_file.resolve().relative_to(root.resolve()).as_posix()
    locked = git("show", f"{TAG}:{relative}")
    if locked.returncode != 0:
        return f"{relative} is not part of {TAG}"
    if locked.stdout != params_file.read_bytes():
        return (
            f"{relative} differs from its {TAG} version: every change after the lock must be "
            "logged in the decision log (constitution III)"
        )
    return None


def require(root: Path, params_file: Path) -> None:
    """Raise `NotLocked` unless the pre-registration is locked (see `problem`)."""
    reason = problem(root, params_file)
    if reason is not None:
        raise NotLocked(reason)
