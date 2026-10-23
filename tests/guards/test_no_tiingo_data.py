"""No real Tiingo data is ever committed (constitution VI; Tiingo ToS §1.6): test data for Tiingo
is generated at run time from synthetic values, never stored under tests/ (T065)."""

import subprocess

from conftest import REPO

HEADER = "date,close,high,low,open,volume,adjClose"


def test_no_file_under_tests_holds_tiingo_price_data():
    offenders = []
    for path in (REPO / "tests").rglob("*"):
        if not path.is_file() or path.suffix in (".pyc",):
            continue
        if path.suffix != ".py" and "tiingo" in path.name.lower():
            offenders.append(path.relative_to(REPO).as_posix())
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if HEADER in text and "# synthetic" not in text:
            offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == []


def test_no_tracked_file_is_tiingo_data():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    assert [
        f for f in tracked if f.startswith("data/") or f.endswith((".csv.gz", ".json.gz"))
    ] == []
