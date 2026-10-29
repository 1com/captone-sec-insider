"""The risk pre-registration lock: risk labels are computed only when the tag `prereg-risk-v5`
exists and `config/risk_params.yaml` is byte-identical to its version at the tag. The check is local
(no network), so a rebuild from a clone can run it."""

import subprocess

from sentinel.config import Paths

TAG = "prereg-risk-v5"  # v5: D63 as amended; v4, v3, v2 (D61) and v1 stay as history


class NotLocked(Exception):
    """The registration is not locked, or the parameter file changed since the lock."""


def problem(p: Paths, tag: str = TAG) -> str | None:
    """None when `tag` exists and the risk parameter file equals its version at the tag."""

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=p.root, capture_output=True)

    if git("rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode != 0:
        return f"tag {tag} not found: fetch the tags (git fetch --tags)"
    relative = p.risk_params_file.resolve().relative_to(p.root.resolve()).as_posix()
    locked = git("show", f"{tag}:{relative}")
    if locked.returncode != 0:
        return f"{relative} is not part of {tag}"
    if locked.stdout != p.risk_params_file.read_bytes():
        return (f"{relative} differs from its {tag} version: every change after the lock must be "
                "logged in docs/decisions.md and tagged anew")  # fmt: skip
    return None


def require(p: Paths, tag: str = TAG) -> None:
    reason = problem(p, tag)
    if reason is not None:
        raise NotLocked(reason)
