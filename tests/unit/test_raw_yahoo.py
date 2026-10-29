"""Yahoo downloads: the daily window of every listed symbol, and full histories (a stand-in for
`yfinance.download`; no network)."""

import json
from datetime import date

import pandas as pd
import pytest

from sentinel.raw import yahoo
from sentinel.raw.manifest import Manifest, store_bytes

QUIET = {"echo": lambda s: None, "sleep": lambda s: None}
TODAY = date(2026, 10, 30)


class StandIn:
    """Answers like `yfinance.download(group_by="ticker")`: two days per symbol, none for NODATA;
    `events` maps a symbol to (dividend, split) on the last day."""

    def __init__(self, events=None):
        self.calls, self.events = [], events or {}

    def __call__(self, tickers, start, **kwargs):
        self.calls.append((list(tickers), start))
        days = pd.DatetimeIndex(["2026-10-28", "2026-10-29"], name="Date")
        cols = {}
        for t in tickers:
            if t == "NODATA":
                continue
            dividend, split = self.events.get(t, (0.0, 0.0))
            values = {"Open": [10.0, 11.0], "High": [10.0, 11.0], "Low": [10.0, 11.0],
                      "Close": [10.0, 11.0], "Adj Close": [10.0, 11.0], "Volume": [100, 200],
                      "Dividends": [0.0, dividend], "Stock Splits": [0.0, split]}  # fmt: skip
            cols |= {(t, f): v for f, v in values.items()}
        return pd.DataFrame(cols, index=days)


@pytest.fixture
def listed(tmp_data):
    """A stored SEC ticker list: Apple, Berkshire's class B, a symbol Yahoo does not have."""
    doc = {"fields": ["cik", "name", "ticker", "exchange"],
           "data": [[320193, "Apple", "AAPL", "Nasdaq"], [1067983, "Berkshire", "BRK.B", "NYSE"],
                    [1, "Nothing", "NODATA", "OTC"]]}  # fmt: skip
    store_bytes(tmp_data, Manifest(tmp_data.manifest), "sec_company_tickers",
                "sec/reference/company_tickers_exchange_20261030.json", "20261030",
                json.dumps(doc).encode(), "https://www.sec.gov/files/x.json")  # fmt: skip
    return tmp_data


def test_the_window_covers_every_listed_symbol_and_the_index_funds_once_a_day(listed):
    fetch = StandIn()
    report = yahoo.fetch_window(listed, TODAY, fetch=fetch, **QUIET)
    assert fetch.calls == [(["AAPL", "BRK-B", "IWM", "NODATA", "SPY"], "2026-10-20")]
    rows = pd.read_parquet(listed.raw / "yahoo/daily/2026-10-30/batch-000.parquet")
    assert sorted(rows["ticker"].unique()) == ["AAPL", "BRK-B", "IWM", "SPY"]
    assert list(rows.columns) == ["ticker", "Date", *yahoo.FIELDS]
    assert report.files_stored == 1 and report.latest_date == date(2026, 10, 29)
    entry = Manifest(listed.manifest).find_original("yahoo", "daily/2026-10-30/000")
    assert entry.url == "yfinance.download(start=2026-10-20, auto_adjust=False, actions=True)"
    again = yahoo.fetch_window(listed, TODAY, fetch=fetch, **QUIET)
    assert again.files_stored == 0 and len(fetch.calls) == 1  # once a day


def test_full_histories_are_fetched_once_and_symbols_without_data_are_remembered(listed):
    fetch = StandIn()
    yahoo.fetch_window(listed, TODAY, fetch=fetch, full_missing=True, **QUIET)
    book = Manifest(listed.manifest)
    histories = sorted(e.key for e in book.originals("yahoo") if e.key.startswith("history/"))
    assert histories == [f"history/{t}/2026-10-30" for t in ("AAPL", "BRK-B", "IWM", "SPY")]
    assert "NODATA,no_data" in (listed.raw / "yahoo/history/failures.csv").read_text()
    assert yahoo.missing_histories(listed, book, yahoo.listed_symbols(listed, book)) == []
