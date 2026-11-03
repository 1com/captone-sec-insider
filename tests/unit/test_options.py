"""Unit tests for Feature 023: Options benchmark and on-demand option chains."""

from datetime import date
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from sentinel.app.main import app
from sentinel.cli import app as cli_app
from sentinel.core import options as core_options
from sentinel.raw.options import fetch_option_chain_data


@pytest.fixture
def client():
    return TestClient(app)


def test_fetch_option_chain_data_mock():
    """Test option chain parsing, mid_price computation, and max_days filtering."""
    calls_df = pd.DataFrame(
        [
            {
                "strike": 100.0,
                "lastPrice": 5.0,
                "bid": 4.8,
                "ask": 5.2,
                "volume": 100,
                "openInterest": 500,
                "impliedVolatility": 0.25,
                "inTheMoney": True,
                "contractSymbol": "TEST261201C00100000",
            }
        ]
    )
    puts_df = pd.DataFrame(
        [
            {
                "strike": 100.0,
                "lastPrice": 4.5,
                "bid": 4.3,
                "ask": 4.7,
                "volume": 80,
                "openInterest": 400,
                "impliedVolatility": 0.24,
                "inTheMoney": False,
                "contractSymbol": "TEST261201P00100000",
            }
        ]
    )

    mock_chain = MagicMock()
    mock_chain.calls = calls_df
    mock_chain.puts = puts_df

    mock_ticker = MagicMock()
    mock_ticker.options = ("2026-12-01", "2028-01-01")  # one valid, one > 365d
    mock_ticker.option_chain.return_value = mock_chain

    with patch("yfinance.Ticker", return_value=mock_ticker):
        df = fetch_option_chain_data("TEST", as_of=date(2026, 11, 1), max_days=365)

    assert not df.empty
    assert len(df) == 2  # 1 call + 1 put for 2026-12-01 (2028 excluded)
    assert set(df["option_type"]) == {"call", "put"}
    assert df["ticker"].iloc[0] == "TEST"
    assert df["days_to_exp"].iloc[0] == 30
    assert df["mid_price"].iloc[0] == 5.0  # (4.8 + 5.2)/2


def test_save_option_chain_and_summary():
    """Test DuckDB table creation, idempotent insertion, and IV calculations."""
    con = duckdb.connect(":memory:")
    today = date(2026, 11, 1)

    # Synthetic options contracts covering 30d, 60d, 90d
    records = [
        # 30-day contracts (exp: 2026-12-01)
        {
            "ticker": "AAPL",
            "as_of": today,
            "expiration": date(2026, 12, 1),
            "days_to_exp": 30,
            "option_type": "call",
            "strike": 200.0,
            "last_price": 5.0,
            "bid": 4.9,
            "ask": 5.1,
            "mid_price": 5.0,
            "volume": 1000,
            "open_interest": 5000,
            "implied_volatility": 0.20,
            "in_the_money": True,
            "contract_symbol": "AAPL261201C200",
        },
        {
            "ticker": "AAPL",
            "as_of": today,
            "expiration": date(2026, 12, 1),
            "days_to_exp": 30,
            "option_type": "put",
            "strike": 200.0,
            "last_price": 4.8,
            "bid": 4.7,
            "ask": 4.9,
            "mid_price": 4.8,
            "volume": 500,
            "open_interest": 3000,
            "implied_volatility": 0.22,
            "in_the_money": False,
            "contract_symbol": "AAPL261201P200",
        },
        # 90-day contracts (exp: 2027-01-30)
        {
            "ticker": "AAPL",
            "as_of": today,
            "expiration": date(2027, 1, 30),
            "days_to_exp": 90,
            "option_type": "call",
            "strike": 200.0,
            "last_price": 8.0,
            "bid": 7.8,
            "ask": 8.2,
            "mid_price": 8.0,
            "volume": 800,
            "open_interest": 4000,
            "implied_volatility": 0.25,
            "in_the_money": True,
            "contract_symbol": "AAPL270130C200",
        },
    ]
    df = pd.DataFrame(records)

    # 1. Save
    inserted = core_options.save_option_chain(con, df)
    assert inserted == 3

    # Idempotent re-run
    re_inserted = core_options.save_option_chain(con, df)
    assert re_inserted == 3
    count = con.execute("select count(*) from core.option_chain").fetchone()[0]
    assert count == 3

    # 2. Compute Summary
    summary = core_options.compute_option_summary(con, "AAPL", as_of=today)
    assert summary["ticker"] == "AAPL"
    assert summary["call_volume"] == 1800
    assert summary["put_volume"] == 500
    assert round(summary["put_call_ratio"], 2) == 0.28
    assert summary["atm_iv_30d"] is not None
    assert summary["atm_iv_90d"] is not None


def test_api_options_endpoint(client):
    """Test the /api/options/{ticker} endpoint."""
    res = client.get("/api/options/AAPL")
    assert res.status_code == 200
    data = res.json()
    assert data["ticker"] == "AAPL"
    assert "summary" in data
    assert "expirations" in data
    assert "contracts" in data
    assert isinstance(data["contracts"], list)


def test_cli_options_mock():
    """Test CLI command sentinel options with mocked yfinance."""
    runner = CliRunner()
    mock_df = pd.DataFrame(
        [
            {
                "ticker": "MSFT",
                "as_of": date(2026, 11, 1),
                "expiration": date(2026, 12, 1),
                "days_to_exp": 30,
                "option_type": "call",
                "strike": 400.0,
                "last_price": 10.0,
                "bid": 9.8,
                "ask": 10.2,
                "mid_price": 10.0,
                "volume": 200,
                "open_interest": 1000,
                "implied_volatility": 0.22,
                "in_the_money": False,
                "contract_symbol": "MSFT261201C400",
            }
        ]
    )

    with patch("sentinel.raw.options.fetch_option_chain_data", return_value=mock_df):
        res = runner.invoke(cli_app, ["options", "MSFT", "--no-save"])
        assert res.exit_code == 0
        assert "MSFT" in res.output
        assert "Found 1 contracts" in res.output
