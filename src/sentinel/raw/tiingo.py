"""Tiingo daily prices while the paid plan lasts (port of v1's `ingest/tiingo.py`; research R7).

`fetch_new_days`: for each listed company priced from Tiingo (`ref.security`), the days after its
last staged session, as Tiingo's daily CSV stored gzip-compressed at
`tiingo/daily/<date>/<T>.csv.gz`. Outside `[tiingo.paid_from, tiingo.paid_until)` nothing is asked
(constitution VI). The token travels in a header only: never in a URL, the manifest or a log.
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
    echo(f"  tiingo: {len(todo):,} Tiingo-priced listed companies, {report.files_stored:,} with "
         f"new days")  # fmt: skip
    return report
