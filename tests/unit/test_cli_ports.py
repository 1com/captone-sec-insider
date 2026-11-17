"""The port check of `sentinel web` (AGENTS.md section 5): ports 8000 and 8080 belong to other
projects and are never used, a busy port is refused (here in WSL and on Windows), and nothing is
ever stopped.

Moved from the old app's tests, which checked the same rule through `sentinel serve`; that command
was removed with the old app (17 Nov 2026, V2-76)."""

import socket

import pytest
from typer.testing import CliRunner

from sentinel import cli
from sentinel.cli import _listening
from sentinel.cli import app as cli_app


def test_web_refuses_the_other_projects_ports(monkeypatch):
    import uvicorn

    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("the server was started"))
    for port in (8000, 8080):
        res = CliRunner().invoke(cli_app, ["web", "--port", str(port)])
        assert res.exit_code == 2 and f"Port {port} is reserved" in res.stderr


def test_web_refuses_a_busy_port_and_starts_on_a_free_one(monkeypatch):
    import uvicorn

    started = []
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append((a, k)))
    monkeypatch.setattr(cli, "NETSTAT", "/nonexistent/netstat.exe")  # Windows is not asked here
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        res = CliRunner().invoke(cli_app, ["web", "--port", str(port)])
        assert res.exit_code == 2 and "in use here" in res.stderr and not started
    res = CliRunner().invoke(cli_app, ["web", "--port", str(port)])  # closed: free again
    assert res.exit_code == 0
    assert started == [
        (("sentinel.web.main:app",), {"host": "127.0.0.1", "port": port, "log_level": "warning"})
    ]


def test_windows_listening_ports_are_read_whatever_the_language():
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
