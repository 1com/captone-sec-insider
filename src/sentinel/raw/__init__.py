"""Layer 1: downloads into `data/raw/` (docs/architecture.md), one module per source.

`fetchers()` maps each `sentinel fetch <source>` name to its function
(specs/001-daily-data-refresh/contracts/cli.md). A fetcher takes the paths, today's date and its
options, stores every file through the manifest, and returns a `FetchReport`. `run` holds the raw
fetch lock; `all` runs the sources in parallel threads, each within its own provider's limits, and
one source's failure never stops the others.
"""

import contextlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date

from sentinel import db
from sentinel.config import ConfigError, Paths
from sentinel.raw.manifest import FetchLock

DAILY = ("sec-tickers", "sec-daily", "form4", "yahoo", "tiingo", "fred", "cboe", "finra")


@dataclass
class FetchReport:
    source: str
    requests: int = 0
    files_stored: int = 0
    bytes: int = 0
    latest_date: date | None = None
    errors: list[str] = field(default_factory=list)
    skipped: str | None = None  # why nothing was asked (e.g. "plan ended")

    def stored(self, n_bytes: int) -> None:
        self.files_stored += 1
        self.bytes += n_bytes

    @property
    def status(self) -> str:
        if self.errors:
            return "failed"
        if self.skipped:
            return f"skipped: {self.skipped}"
        return "fetched" if self.files_stored else "nothing_new"

    def summary(self) -> str:
        line = (f"{self.source}: {self.status}; {self.files_stored:,} files "
                f"({self.bytes / 1e6:,.1f} MB) in {self.requests:,} requests")  # fmt: skip
        if self.latest_date:
            line += f"; latest {self.latest_date}"
        if self.errors:
            line += f"; {len(self.errors):,} errors, first: {self.errors[0]}"
        return line


Fetcher = Callable[..., FetchReport]


@contextlib.contextmanager
def reader(p: Paths, con):
    """For fetchers that read the build database (who is a company, which tickers Tiingo prices):
    the caller's connection, or a read-only one."""
    if con is not None:
        yield con
        return
    if not p.build_db.exists():
        raise db.MissingInput("the build database is missing: run `sentinel build` first")
    connection = db.connect(p, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def fetchers() -> dict[str, Fetcher]:
    """Every source's fetch function."""
    from sentinel.raw import market, sec, tiingo, yahoo

    return {
        "sec-tickers": sec.fetch_tickers,
        "sec-daily": sec.fetch_daily,
        "sec-bulk": sec.fetch_bulk,
        "yahoo": yahoo.fetch_window,
        "tiingo": tiingo.fetch_new_days,
        "fred": market.fetch_fred,
        "cboe": market.fetch_cboe,
        "finra": market.fetch_finra,
    }


def _one(name: str, fetch: Fetcher, p: Paths, today: date, echo, con, options) -> FetchReport:
    try:
        return fetch(p, today, echo=echo, con=con, **options)
    except Exception as e:  # a failing source is reported, the others go on (spec FR-018)
        report = FetchReport(name)
        report.errors.append(f"{type(e).__name__}: {e}"[:300])
        return report


def run(p: Paths, source: str, today: date, echo=print, con=None, **options) -> list[FetchReport]:
    """Fetch one source, or with `all` every daily source: the SEC ticker list first (the Yahoo
    window asks for its symbols), then the rest in parallel. `con` is the caller's database
    connection, shared through cursors (the update holds the database open)."""
    known = fetchers()
    cursor = (lambda: con.cursor()) if con is not None else (lambda: None)
    with FetchLock(p.lock):
        if source != "all":
            try:
                return [known[source](p, today, echo=echo, con=cursor(), **options)]
            except ConfigError:
                raise
            except Exception as e:
                return [FetchReport(source, errors=[f"{type(e).__name__}: {e}"[:300]])]
        first = [n for n in DAILY[:1] if n in known]
        rest = [n for n in DAILY[1:] if n in known]
        reports = [_one(n, known[n], p, today, echo, cursor(), options) for n in first]
        with ThreadPoolExecutor(max_workers=max(len(rest), 1)) as pool:
            futures = [pool.submit(_one, n, known[n], p, today, echo, cursor(), options)
                       for n in rest]  # fmt: skip
            return reports + [f.result() for f in futures]
