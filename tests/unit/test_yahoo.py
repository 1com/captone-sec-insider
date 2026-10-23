"""Yahoo prices: storage as received, resume, failures, universe and primary tickers (T010)."""

import stat
from datetime import date

import duckdb
import pandas as pd
import pytest
from conftest import yahoo_frame

from sentinel.ingest import manifest, yahoo

D = [date(2019, 1, 2), date(2019, 1, 3)]


def _rows(close):
    return [{"session": d, "close": close} for d in D]


class FakeYahoo:
    """Stands in for `yf.download`: returns a frame for the tickers it knows, or raises."""

    def __init__(self, known: dict, fail_times: int = 0):
        self.known, self.fail_times, self.calls = known, fail_times, []

    def __call__(self, tickers, **kwargs):
        self.calls.append((list(tickers), kwargs))
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("rate limited")
        return yahoo_frame({t: self.known[t] for t in tickers if t in self.known})


def _download(tmp_data, params, tickers, fake, **kw):
    return yahoo.download(tmp_data, params, tickers, fetch=fake, sleep=lambda s: None, **kw)


def test_each_ticker_is_stored_as_received_with_a_manifest_line(tmp_data, params):
    fake = FakeYahoo({"AAA": _rows(5.0), "BBB": _rows(7.0)})
    report = _download(tmp_data, params, ["AAA", "BBB"], fake)
    assert (report.stored, report.failed) == (2, [])
    path = tmp_data.yahoo / "AAA.parquet"
    frame = pd.read_parquet(path)
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Adj Close", "Volume",
                                   "Dividends", "Stock Splits"]  # fmt: skip
    assert frame["Close"].tolist() == [5.0, 5.0]
    assert not path.stat().st_mode & stat.S_IWUSR  # read-only once stored
    entry = manifest.find_original(tmp_data.manifest, "yahoo", "AAA")
    assert entry.path == "yahoo/AAA.parquet"
    assert entry.url == "yfinance.download(start=2010-01-01, auto_adjust=False, actions=True)"
    assert entry.sha256 == manifest.sha256_file(path)
    _, kwargs = fake.calls[0]
    assert kwargs["start"] == "2010-01-01" and kwargs["auto_adjust"] is False
    assert kwargs["actions"] is True and kwargs["group_by"] == "ticker"


def test_a_rerun_skips_stored_tickers(tmp_data, params):
    _download(tmp_data, params, ["AAA"], FakeYahoo({"AAA": _rows(5.0)}))
    again = FakeYahoo({"AAA": _rows(9.0)})
    report = _download(tmp_data, params, ["AAA"], again)
    assert again.calls == [] and report.cached == 1 and report.stored == 0


def test_a_failing_batch_is_retried_three_times_then_listed(tmp_data, params):
    fake = FakeYahoo({"AAA": _rows(5.0)}, fail_times=3)
    report = _download(tmp_data, params, ["AAA"], fake)
    assert len(fake.calls) == 3
    assert report.failed == [("AAA", "download_error")]
    failures = pd.read_csv(tmp_data.yahoo / "failures.csv")
    assert failures.to_dict("records") == [{"ticker": "AAA", "reason": "download_error"}]
    # Earlier failures are skipped unless asked for again
    later = FakeYahoo({"AAA": _rows(5.0)})
    assert _download(tmp_data, params, ["AAA"], later).skipped_failed == 1 and later.calls == []
    assert _download(tmp_data, params, ["AAA"], later, retry_failures=True).stored == 1
    assert not (tmp_data.yahoo / "failures.csv").exists()


def test_a_ticker_without_data_is_a_failure(tmp_data, params):
    report = _download(tmp_data, params, ["AAA", "GONE"], FakeYahoo({"AAA": _rows(5.0)}))
    assert report.stored == 1 and report.failed == [("GONE", "no_data")]


def test_limit_caps_the_number_fetched(tmp_data, params):
    fake = FakeYahoo({t: _rows(1.0) for t in ("A", "B", "C")})
    assert _download(tmp_data, params, ["A", "B", "C"], fake, limit=2).stored == 2


@pytest.fixture
def con():
    con = duckdb.connect()
    for schema in ("core", "evt"):
        con.execute(f"create schema {schema}")
    con.execute(
        "create table core.symbol_map (issuer_cik VARCHAR, ticker VARCHAR, valid_from DATE, "
        "valid_to DATE, price_source VARCHAR, match_quality VARCHAR)"
    )
    con.execute("create table evt.prelim_event (issuer_cik VARCHAR, signal_date DATE)")
    con.execute(
        "create table core.filing (accession VARCHAR, issuer_cik VARCHAR, filing_date DATE, "
        "symbol_raw VARCHAR)"
    )
    con.executemany(
        "insert into core.symbol_map values (?, ?, '2010-01-01', null, ?, 'sec_current')",
        [("1", "BRK-A", "yahoo"), ("1", "BRK-B", "yahoo"), ("2", "OLD", "yahoo"),
         ("3", "DEAD", "tiingo"), ("4", "ZZZ", "yahoo")],
    )  # fmt: skip
    con.executemany(
        "insert into evt.prelim_event values (?, ?)",
        [("1", "2015-01-05"), ("2", "2011-06-30"), ("3", "2016-02-01"), ("4", "2020-01-02")],
    )
    con.executemany(
        "insert into core.filing values (?, ?, '2015-01-01', ?)",
        [("a1", "1", "BRK-B"), ("a2", "1", "brk.b"), ("a3", "1", "BRK-A"), ("a4", "4", None)],
    )
    return con


def test_universe_tickers_are_yahoo_mapped_issuers_with_events_from_the_start(con, params):
    # Issuer 2's only event is before 2011-07-01; issuer 3 is Tiingo-mapped.
    assert yahoo.universe_tickers(con, params) == ["BRK-A", "BRK-B", "IWM", "SPY", "ZZZ"]


def test_primary_ticker_is_the_one_most_reported_in_form4s(con):
    # BRK-B is reported twice (once as "brk.b"), BRK-A once; ZZZ has no reported symbol.
    assert yahoo.primary_tickers(con) == {"1": "BRK-B", "2": "OLD", "4": "ZZZ"}


def test_primary_ticker_ties_break_alphabetically(con):
    con.execute("insert into core.filing values ('a5', '1', '2015-02-01', 'BRK-A')")
    assert yahoo.primary_tickers(con)["1"] == "BRK-A"
