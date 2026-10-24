"""The stock lookup on the real data (feature 005; SC-001, SC-002, SC-003, SC-007).

Run with `uv run pytest -m slow` after `sentinel lookup`; skipped when `data/lookup.duckdb` is
absent.
"""

import re
import time

import pytest
from conftest import REPO

from sentinel.api import glossary, queries
from sentinel.config import Paths

PATHS = Paths.from_root(REPO)
PAYPAL, DORMAN = "1633917", "1082870"
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not PATHS.lookup.exists(), reason="needs data/lookup.duckdb"),
]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from sentinel.api.app import create_app

    with TestClient(create_app(PATHS)) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def cur():
    con = queries.open_lookup(PATHS)
    yield queries.cursor(con)
    con.close()


def test_every_code_in_the_data_has_a_description(cur):
    codes = [
        c for (c,) in cur.execute("select distinct trans_code from lookup.transaction").fetchall()
    ]
    undescribed = [c for c in codes if c and c.strip() and c.strip().upper() not in glossary.CODES]
    assert codes and not undescribed


@pytest.mark.parametrize(
    ("q", "cik"), [("PYPL", PAYPAL), ("paypal", PAYPAL), (PAYPAL, PAYPAL), ("SIVB", "719739")]
)
def test_searches_find_the_right_company_first(client, q, cik):
    assert client.get("/api/issuers/search", params={"q": q}).json()["results"][0]["cik"] == cik


def test_the_largest_company_opens_within_two_seconds(client, cur):
    cik, n = cur.execute(
        "select issuer_cik, count(*) from lookup.transaction group by 1 order by 2 desc limit 1"
    ).fetchone()
    assert n > 50_000
    for url in (f"/company/{cik}", f"/api/issuers/{cik}/transactions"):
        start = time.perf_counter()
        response = client.get(url)
        elapsed = time.perf_counter() - start
        assert response.status_code == 200 and elapsed < 2, (url, elapsed)


def test_paypal_shows_the_cluster_and_dormans_holdings(client):
    page = client.get(f"/company/{PAYPAL}").text
    card = re.search(r'data-event="1633917:A:2021-11-23">(.*?)</article>', page, re.S).group(1)
    assert "$2,287,696.69" in card and "DORMAN DAVID W" in card
    assert len(re.findall(r"https://www.sec.gov/Archives/edgar/data/1633917/\d+/", card)) == 2
    holdings = client.get(f"/company/{PAYPAL}/insider/{DORMAN}").text
    row = re.search(r'<tr data-date="2021-11-23" data-security="[^"]*">(.*?)</tr>', holdings, re.S)
    assert row and "44,890" in row.group(1) and "46,437" in row.group(1)
