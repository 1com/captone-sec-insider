"""The real warehouse satisfies every invariant (T038). Run with `uv run pytest -m slow`."""

import pytest
from conftest import REPO

from sentinel import warehouse
from sentinel.config import Paths
from sentinel.ingest.sec_reference import latest_snapshot

pytestmark = pytest.mark.slow


def test_the_real_warehouse_satisfies_every_invariant(params):
    paths = Paths.from_root(REPO)
    con = warehouse.connect(paths, read_only=True)
    try:
        assert warehouse.check_invariants(con, params, latest_snapshot(paths)) == []
    finally:
        con.close()
