"""Tiingo daily prices while the paid plan lasts (port of v1's `ingest/tiingo.py`; research R7).

`fetch_new_days`: for each listed company priced from Tiingo (`ref.security`), the days after its
last staged session, as Tiingo's daily CSV stored gzip-compressed at
`tiingo/daily/<date>/<T>.csv.gz`. Outside `[tiingo.paid_from, tiingo.paid_until)` nothing is asked
(constitution VI). The token travels in a header only: never in a URL, the manifest or a log.

`fetch_former` (feature 027, research R9): once, for each ticker a company's own evidence names
(its Form 4 symbols, the SEC's lists) with no stored series, whose lines in Tiingo's list overlap
the company's use: the whole series from `prices.history_start` (`tiingo/former/<T>.csv.gz`) and
Tiingo's description (`tiingo/former_meta/<T>.json.gz`), so a company that changed its ticker can
keep its history under the old one.
"""

from datetime import date, timedelta

import httpx

from sentinel import __version__, db
from sentinel.config import ConfigError, Paths, in_tiingo_window, secrets, sources
from sentinel.raw import FetchReport, reader
from sentinel.raw.http import RateLimiter, RetryPolicy, SecForbidden, request_with_retry
from sentinel.raw.manifest import Manifest, store_gz

SOURCE = "tiingo"


def make_client(api_key: str, timeout: float) -> httpx.Client:
    """A generic User-Agent: the SEC contact is not sent to Tiingo."""
    return httpx.Client(
        headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json",
                 "User-Agent": f"edgar-sentinel/{__version__}"},
        timeout=timeout, follow_redirects=True,
    )  # fmt: skip


def targets(con) -> list[tuple[str, date | None]]:
    """(ticker, last staged session) of each listed company priced from Tiingo."""
    db.require(con, ["ref.security", "stg_tiingo.price"], "sentinel fetch tiingo")
    return con.execute(
        """
        select s.ticker, max(t.session) from ref.security s
        left join stg_tiingo.price t on t.ticker = s.ticker
        where s.source = 'tiingo' and s.listed group by 1 order by 1
        """
    ).fetchall()


def fetch_new_days(p: Paths, today: date, echo=print, con=None, **_) -> FetchReport:
    report = FetchReport("tiingo")
    settings = sources(p)
    if not in_tiingo_window(settings, today):
        started = today >= settings["tiingo"]["paid_from"]
        report.skipped = "plan ended" if started else "plan not started"
        return report
    key = secrets(p).tiingo_api
    if not key:
        raise ConfigError("TIINGO_API missing in .env")
    with reader(p, con) as r:
        todo = targets(r)
    t = settings["tiingo"]
    limiter = RateLimiter(t["requests_per_second"], t["requests_per_second"])
    policy = RetryPolicy.from_settings(settings["http"])
    book = Manifest(p.manifest)
    with make_client(key, settings["http"]["timeout_seconds"]) as client:
        for ticker, last in todo:
            k = f"daily/{today}/{ticker}"
            start = last + timedelta(days=1) if last else settings["prices"]["history_start"]
            if start > today or book.find_original(SOURCE, k):
                continue
            url = f"{t['api_base']}/{ticker}/prices?startDate={start}&format=csv&resampleFreq=daily"
            report.requests += 1
            try:
                resp = request_with_retry(client, "GET", url, limiter, policy)
            except SecForbidden as e:  # a refused token or plan: no point asking for the rest
                raise RuntimeError("Tiingo answered 403: check TIINGO_API and the plan") from e
            if resp.status_code != 200:
                report.errors.append(f"{ticker}: HTTP {resp.status_code}")
                continue
            lines = resp.text.strip().splitlines()
            if len(lines) < 2 or not lines[0].startswith("date,"):
                continue  # no new day yet
            rel = f"tiingo/daily/{today}/{ticker}.csv.gz"
            store_gz(p, book, SOURCE, rel, k, resp.content, url)
            report.stored((p.raw / rel).stat().st_size)
            latest = date.fromisoformat(lines[-1][:10])
            report.latest_date = max(report.latest_date or latest, latest)
            if _has_event(lines):  # Tiingo rewrites the adjusted past: the whole series again
                history = f"{t['api_base']}/{ticker}/prices?startDate="
                history += f"{settings['prices']['history_start']}&format=csv&resampleFreq=daily"
                report.requests += 1
                resp = request_with_retry(client, "GET", history, limiter, policy)
                if resp.status_code == 200:
                    rel = f"tiingo/history/{today}/{ticker}.csv.gz"
                    store_gz(p, book, SOURCE, rel, f"history/{ticker}/{today}", resp.content,
                             history)  # fmt: skip
                    report.stored((p.raw / rel).stat().st_size)
                else:
                    report.errors.append(f"{ticker} history: HTTP {resp.status_code}")
    echo(f"  tiingo: {len(todo):,} Tiingo-priced listed companies, {report.files_stored:,} files")
    return report


def _has_event(lines: list[str]) -> bool:
    """Whether Tiingo's daily CSV shows a dividend (`divCash`) or a split (`splitFactor` ≠ 1)."""
    head = lines[0].split(",")
    div, split = head.index("divCash"), head.index("splitFactor")
    for line in lines[1:]:
        cells = line.split(",")
        if float(cells[div] or 0) != 0 or float(cells[split] or 1) != 1:
            return True
    return False


def former_targets(con) -> list[str]:
    """Tickers named by a company's own evidence with no stored Yahoo or Tiingo series, which
    Tiingo's list carries with dates overlapping the company's use (research R9)."""
    db.require(con, ["ref.ticker_history", "stg_tiingo.listing", "stg_tiingo.price",
                     "stg_yahoo.price"], "sentinel fetch tiingo-former")  # fmt: skip
    rows = con.execute(
        """
        with stored as (select distinct ticker from stg_tiingo.price
                        union select distinct ticker from stg_yahoo.price),
        listing as (select upper(replace(replace(ticker, '.', '-'), '/', '-')) as ticker,
                           start_date, end_date from stg_tiingo.listing
                    where asset_type = 'Stock' and currency = 'USD')
        select distinct h.ticker from ref.ticker_history h
        join listing l on l.ticker = h.ticker
             and l.start_date <= coalesce(h.valid_to, current_date)
             and coalesce(l.end_date, current_date) >= h.valid_from
             and coalesce(l.end_date, current_date) >= DATE '2010-01-01'
        where h.ticker not in (select ticker from stored)
          and coalesce(h.valid_to, current_date) >= DATE '2010-01-01'
        order by 1
        """
    ).fetchall()
    return [t for (t,) in rows]


def fetch_former(p: Paths, today: date, echo=print, con=None, **_) -> FetchReport:
    report = FetchReport("tiingo-former")
    settings = sources(p)
    if not in_tiingo_window(settings, today):
        started = today >= settings["tiingo"]["paid_from"]
        report.skipped = "plan ended" if started else "plan not started"
        return report
    key = secrets(p).tiingo_api
    if not key:
        raise ConfigError("TIINGO_API missing in .env")
    with reader(p, con) as r:
        todo = former_targets(r)
    t = settings["tiingo"]
    limiter = RateLimiter(t["requests_per_second"], t["requests_per_second"])
    policy = RetryPolicy.from_settings(settings["http"])
    book = Manifest(p.manifest)
    start = settings["prices"]["history_start"]
    without_data = 0
    with make_client(key, settings["http"]["timeout_seconds"]) as client:
        for ticker in todo:
            prices = f"{t['api_base']}/{ticker}/prices?startDate={start}&format=csv"
            asks = (
                (
                    "former_meta",
                    f"{t['api_base']}/{ticker}",
                    f"tiingo/former_meta/{ticker}.json.gz",
                ),
                ("former", prices + "&resampleFreq=daily", f"tiingo/former/{ticker}.csv.gz"),
            )
            for kind, url, rel in asks:
                k = f"{kind}/{ticker}"
                if book.find_original(SOURCE, k):
                    continue
                report.requests += 1
                try:
                    resp = request_with_retry(client, "GET", url, limiter, policy)
                except SecForbidden as e:  # a refused token or plan: no point asking for the rest
                    raise RuntimeError("Tiingo answered 403: check TIINGO_API and the plan") from e
                if resp.status_code == 404:
                    without_data += kind == "former"
                    continue
                if resp.status_code != 200:
                    report.errors.append(f"{ticker} {kind}: HTTP {resp.status_code}")
                    continue
                if kind == "former" and len(resp.text.strip().splitlines()) < 2:
                    without_data += 1  # stored all the same, so it is not asked again
                store_gz(p, book, SOURCE, rel, k, resp.content, url)
                report.stored((p.raw / rel).stat().st_size)
    echo(f"  tiingo-former: {len(todo):,} old tickers, {report.files_stored:,} files, "
         f"{without_data:,} without prices")  # fmt: skip
    return report
