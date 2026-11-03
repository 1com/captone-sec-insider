"""Audit & Smoke Tests for Production Deployment & Public Data Rule (Feature 018).

Ensures all endpoints are reachable and no private Tiingo secrets, internal raw
paths, or unapproved data are served publicly.
"""

import os

import pytest
from fastapi.testclient import TestClient

from sentinel.app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_production_smoke_endpoints(client):
    """Smoke test ensuring every view and API endpoint responds successfully."""
    # 1. Healthcheck / Freshness
    r = client.get("/api/freshness")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)

    # 2. Views
    for path in ["/", "/stock/AAPL", "/screener", "/insiders", "/model-card"]:
        res = client.get(path, follow_redirects=True)
        assert res.status_code == 200, f"Endpoint {path} failed with status {res.status_code}"

    # 3. Core API routes
    assert client.get("/api/search?q=A").status_code == 200
    assert client.get("/api/stock/AAPL").status_code == 200
    assert client.get("/api/prices/AAPL").status_code == 200
    assert client.get("/api/screener?limit=10").status_code == 200
    assert client.get("/api/insiders?limit=10").status_code == 200


def test_public_data_rule_no_secret_leaks(client):
    """Verify that no sensitive environment secrets or internal raw paths leak to clients."""
    # Check if a Tiingo API key or other secret is present in the environment
    secrets_to_check = []
    tiingo_key = os.environ.get("TIINGO_API_KEY")
    if tiingo_key and len(tiingo_key) > 5:
        secrets_to_check.append(tiingo_key)

    forbidden_patterns = [
        "data/raw/",
        "submissions.zip",
        "companyfacts.zip",
        "data/build.duckdb",
        "data/sentinel.duckdb",
    ]

    endpoints_to_probe = [
        "/",
        "/stock/AAPL",
        "/screener",
        "/insiders",
        "/model-card",
        "/api/freshness",
        "/api/search?q=AAPL",
        "/api/stock/AAPL",
        "/api/prices/AAPL",
        "/api/screener",
        "/api/insiders",
    ]

    for ep in endpoints_to_probe:
        res = client.get(ep, follow_redirects=True)
        body = res.text

        # Ensure no internal filesystem / raw paths are leaked
        for pat in forbidden_patterns:
            assert pat not in body, f"Forbidden internal pattern '{pat}' found in {ep}"

        # Ensure no secrets leaked
        for sec in secrets_to_check:
            assert sec not in body, f"Secret key leaked in public endpoint {ep}"
