"""Unit and integration tests for the FastAPI web application and API."""

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from sentinel.app.main import app
from sentinel.cli import app as cli_app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_search(client):
    res = client.get("/api/search?q=A")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) > 0
    first = data[0]
    assert "ticker" in first
    assert "cik" in first
    assert "name" in first


def test_api_stock_and_forecasts(client):
    # Pick the first stock found in search
    search_res = client.get("/api/search?q=A")
    assert search_res.status_code == 200
    first_ticker = search_res.json()[0]["ticker"] or search_res.json()[0]["cik"]

    res = client.get(f"/api/stock/{first_ticker}")
    assert res.status_code == 200
    data = res.json()
    assert "cik" in data
    assert "name" in data
    assert "forecasts" in data
    assert isinstance(data["forecasts"], dict)


def test_api_stock_not_found(client):
    res = client.get("/api/stock/NONEXISTENT_TICKER_XYZ_999")
    assert res.status_code == 404


def test_api_prices(client):
    search_res = client.get("/api/search?q=A")
    assert search_res.status_code == 200
    first_ticker = search_res.json()[0]["ticker"] or search_res.json()[0]["cik"]

    res = client.get(f"/api/prices/{first_ticker}")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_api_screener(client):
    res = client.get("/api/screener?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) <= 10


def test_api_insiders(client):
    res = client.get("/api/insiders?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_html_views(client):
    # 1. Root redirect
    res_root = client.get("/", follow_redirects=False)
    assert res_root.status_code in (302, 307)

    # 2. Screener page
    res_screener = client.get("/screener")
    assert res_screener.status_code == 200
    assert "Market Screener" in res_screener.text

    # 3. Insiders page
    res_insiders = client.get("/insiders")
    assert res_insiders.status_code == 200
    assert "Insider Signal Feed" in res_insiders.text

    # 4. Model card page
    res_mc = client.get("/model-card")
    assert res_mc.status_code == 200
    assert "Model Card" in res_mc.text

    # 5. Stock view (AAPL)
    res_stock = client.get("/stock/AAPL")
    assert res_stock.status_code == 200
    assert "Apple Inc." in res_stock.text
    assert "Volatility" in res_stock.text


def test_cli_serve_protects_port_8000():
    runner = CliRunner()
    res = runner.invoke(cli_app, ["serve", "--port", "8000"])
    assert res.exit_code == 2
    assert "Port 8000 is reserved" in res.stderr


def test_cli_serve_refuses_the_other_projects_ports(monkeypatch):
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("the server was started"))
    for port in (8000, 8080):
        res = CliRunner().invoke(cli_app, ["serve", "--port", str(port)])
        assert res.exit_code == 2 and f"Port {port} is reserved" in res.stderr


def test_cli_serve_refuses_a_busy_port_and_starts_on_a_free_one(monkeypatch):
    import socket

    import uvicorn

    from sentinel import cli

    started = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    monkeypatch.setattr(cli, "NETSTAT", "/nonexistent/netstat.exe")  # Windows is not asked here
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        res = CliRunner().invoke(cli_app, ["serve", "--port", str(port)])
        assert res.exit_code == 2 and "in use here" in res.stderr and not started
    res = CliRunner().invoke(cli_app, ["serve", "--port", str(port)])  # closed: free again
    assert res.exit_code == 0
    assert started == [{"host": "127.0.0.1", "port": port, "reload": False}]


def test_windows_listening_ports_are_read_whatever_the_language():
    from sentinel.cli import _listening

    text = (
        "Aktive Verbindungen\n\n"
        "  Proto  Lokale Adresse         Remoteadresse          Status           PID\n"
        "  TCP    0.0.0.0:135            0.0.0.0:0              ABHÖREN         2032\n"
        "  TCP    127.0.0.1:8080         0.0.0.0:0              ABHÖREN         4\n"
        "  TCP    192.168.1.5:50123      140.82.112.4:443       HERGESTELLT     9\n"
        "  TCP    [::]:8730              [::]:0                 ABHÖREN         7\n"
        "  UDP    0.0.0.0:5353           *:*                                    11\n"
    )
    assert _listening(text) == {135, 8080, 8730}
