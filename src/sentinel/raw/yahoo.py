"""Yahoo daily prices (port of v1's `ingest/yahoo.py`; specs/001-daily-data-refresh, research R6).

- `fetch_window`: the last `prices.yahoo_window_days` days of every symbol in the newest SEC
  ticker list plus the reference symbols (SPY, IWM), in batches of `prices.yahoo_daily_batch_size`,
  one long-format file per batch (`yahoo/daily/<date>/batch-<NNN>.parquet`, a `ticker` column).
- `fetch_history`: a symbol's full history from `prices.history_start`, one file per symbol
  (`yahoo/history/<date>/<T>.parquet`), for symbols never asked (`--full-missing`).

Values are stored as Yahoo gives them (`auto_adjust=False`: the close is split-adjusted, the
adjusted close also dividend-adjusted). Symbols without Yahoo data for a full history go to
`yahoo/history/failures.csv`; v1's failure lists count as asked too.
"""

import csv
import io
import json
import time
from datetime import date, timedelta

import pandas as pd

from sentinel.config import Paths, sources
from sentinel.raw import FetchReport
from sentinel.raw.manifest import Manifest, store_bytes
from sentinel.reference.build import normalise

SOURCE = "yahoo"
FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
ATTEMPTS = 3
FAILURE_FILES = ("yahoo/failures.csv", "yahoo/panel/failures.csv", "yahoo/history/failures.csv")


def _signature(start: date) -> str:
    return f"yfinance.download(start={start}, auto_adjust=False, actions=True)"


def listed_symbols(p: Paths, book: Manifest) -> list[str]:
    """Every symbol of the newest stored SEC ticker list (written as Yahoo writes class shares:
    `BRK-B`), plus the reference symbols, sorted."""
    lists = sorted(book.originals("sec_company_tickers"), key=lambda e: e.key)
    if not lists:
        raise FileNotFoundError("no SEC ticker list stored: run `sentinel fetch sec-tickers`")
    doc = json.loads((p.raw / lists[-1].path).read_text(encoding="utf-8"))
    symbols = {t for row in doc["data"] if (t := normalise(row[2]))}
    return sorted(symbols | set(sources(p)["prices"]["reference_symbols"]))


def _extract(frame, ticker: str):
    """One ticker's rows from a `group_by="ticker"` frame, Yahoo's columns kept; None if empty."""
    if frame is None or frame.empty or ticker not in frame.columns.get_level_values(0):
        return None
    sub = frame[ticker][[c for c in FIELDS if c in frame[ticker].columns]]
    sub = sub.dropna(subset=["Close"])
    if sub.empty:
        return None
    sub.index = sub.index.tz_localize(None) if sub.index.tz is not None else sub.index
    sub.index.name = "Date"
    return sub


def _download(fetch, batch: list[str], start: date, sleep, echo):
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fetch(batch, start=str(start), auto_adjust=False, actions=True,
                         group_by="ticker", threads=True, progress=False, timeout=30)  # fmt: skip
        except Exception as e:  # network or rate limit: back off and retry
            echo(f"  yahoo: attempt {attempt} failed ({type(e).__name__}: {e})"[:200])
            if attempt < ATTEMPTS:
                sleep(5 * attempt)
    return None


def _parquet(frame: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    return buf.getvalue()


def _yfinance():
    import yfinance

    return yfinance.download


def fetch_window(p: Paths, today: date, echo=print, con=None, window_days=None, full_missing=False,
                 fetch=None, sleep=time.sleep, **_) -> FetchReport:  # fmt: skip
    """Today's window for every listed symbol (and, with `full_missing`, full histories first)."""
    fetch = fetch or _yfinance()
    report = FetchReport("yahoo")
    settings = sources(p)["prices"]
    book = Manifest(p.manifest)
    symbols = listed_symbols(p, book)
    if full_missing:
        fetch_history(p, today, missing_histories(p, book, symbols), fetch, sleep, echo, report,
                      book)  # fmt: skip
    start = today - timedelta(days=window_days or settings["yahoo_window_days"])
    size = settings["yahoo_daily_batch_size"]
    for n, i in enumerate(range(0, len(symbols), size)):
        key = f"daily/{today}/{n:03d}"
        if book.find_original(SOURCE, key):
            continue
        batch = symbols[i : i + size]
        report.requests += 1
        frame = _download(fetch, batch, start, sleep, echo)
        if frame is None:
            report.errors.append(f"batch {n:03d}: download failed")
            continue
        parts = []
        for t in batch:
            sub = _extract(frame, t)
            if sub is not None:
                parts.append(sub.reset_index().assign(ticker=t))
        if parts:
            rows = pd.concat(parts, ignore_index=True)[["ticker", "Date", *FIELDS]]
            store_bytes(p, book, SOURCE, f"yahoo/daily/{today}/batch-{n:03d}.parquet", key,
                        _parquet(rows), _signature(start))  # fmt: skip
            report.stored((p.raw / f"yahoo/daily/{today}/batch-{n:03d}.parquet").stat().st_size)
            latest = rows["Date"].max().date()
            report.latest_date = max(report.latest_date or latest, latest)
        if i + size < len(symbols):
            sleep(sources(p)["prices"]["yahoo_pause_seconds"])
    echo(f"  yahoo: {len(symbols):,} symbols in {report.files_stored:,} window files")
    return report


def _failures(p: Paths) -> set[str]:
    out = set()
    for rel in FAILURE_FILES:
        path = p.raw / rel
        if path.exists():
            with open(path, newline="") as f:
                out |= {r["ticker"] for r in csv.DictReader(f)}
    return out


def _add_failures(p: Paths, tickers: list[str]) -> None:
    path = p.raw / "yahoo/history/failures.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    known = _failures(p)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["ticker", "reason"])
        writer.writerows([t, "no_data"] for t in tickers if t not in known)


def missing_histories(p: Paths, book: Manifest, symbols: list[str]) -> list[str]:
    """Symbols with no stored Yahoo history (v1's files or a later one) and no recorded failure."""
    have = set()
    for e in book.originals(SOURCE):
        if not e.key.startswith("daily/"):
            have.add(e.key.removeprefix("panel/").removeprefix("history/").split("/")[0])
    failed = _failures(p)
    return [s for s in symbols if s not in have and s not in failed]


def fetch_history(p: Paths, today: date, symbols: list[str], fetch, sleep, echo,
                  report: FetchReport, book: Manifest) -> None:  # fmt: skip
    """Full histories from `prices.history_start`, one file per symbol, in batches of v1's size."""
    settings = sources(p)["prices"]
    start, size = settings["history_start"], settings["yahoo_batch_size"]
    todo = [s for s in symbols if not book.find_original(SOURCE, f"history/{s}/{today}")]
    echo(f"  yahoo: {len(todo):,} full histories to fetch")
    for i in range(0, len(todo), size):
        batch = todo[i : i + size]
        report.requests += 1
        frame = _download(fetch, batch, start, sleep, echo)
        if frame is None:
            report.errors.append(f"histories {i // size:03d}: download failed")
            continue
        none = []
        for t in batch:
            sub = _extract(frame, t)
            if sub is None:
                none.append(t)
                continue
            rel = f"yahoo/history/{today}/{t}.parquet"
            store_bytes(p, book, SOURCE, rel, f"history/{t}/{today}", _parquet(sub.reset_index()),
                        _signature(start))  # fmt: skip
            report.stored((p.raw / rel).stat().st_size)
        _add_failures(p, none)
        if i + size < len(todo):
            sleep(settings["yahoo_pause_seconds"])
