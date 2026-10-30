"""Market and economic sources (ports of v1's `ingest/fred.py`, `cboe.py` and `finra_short.py`;
research R8). The series and URLs are the registered ones in `config/risk_params.yaml` `sources`.

- `fred`: today's copy of each FRED series: market series as they stand, CPI and unemployment as
  first released (ALFRED `output_type=4`), at `fred/<SERIES>-<mode>-<date>.json.gz`. The API key is
  sent with the request only: never in the stored URL, a log line or an error message.
- `cboe`: today's copy of Cboe's whole VIX history, at `cboe/VIX_History-<date>.csv.gz`.
- `finra`: FINRA's short-volume file per facility and trading day not yet stored, at
  `finra/short_volume/<FACILITY>/<day>.txt.gz`. FINRA's CDN answers 403 for a file that does not
  exist: a day missing for more than `FINRA_GRACE_DAYS` goes to `absent.csv` (a holiday); a newer
  one is simply not published yet and is asked again next run.
"""

import csv
import json
from datetime import date, datetime, timedelta

import httpx

from sentinel import __version__
from sentinel.config import ConfigError, Paths, risk_params, secrets, sources
from sentinel.raw import FetchReport
from sentinel.raw.http import (
    RateLimiter,
    RetryExhausted,
    RetryPolicy,
    SecForbidden,
    request_with_retry,
)
from sentinel.raw.manifest import Manifest, store_gz

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
ALL_REALTIME = {"realtime_start": "1776-07-04", "realtime_end": "9999-12-31"}
FINRA_GRACE_DAYS = 4
AGENT = {"User-Agent": f"edgar-sentinel/{__version__}"}


def fetch_fred(p: Paths, today: date, echo=print, con=None, **_) -> FetchReport:
    report = FetchReport("fred")
    key = secrets(p).fred_api_key
    if not key:
        raise ConfigError("FRED_API_KEY missing in .env")
    rp = risk_params(p)["sources"]
    wanted = [(s, "market") for s in rp["fred_market_series"]]
    wanted += [(s, "first") for s in rp["fred_released_series"]]
    book = Manifest(p.manifest)
    with httpx.Client(headers=AGENT, timeout=sources(p)["http"]["timeout_seconds"]) as client:
        for series, mode in wanted:
            k = f"{series}-{mode}-{today}"
            if book.find_original("fred", k):
                continue
            query = {"series_id": series, "file_type": "json"}
            if mode == "first":
                query |= {"output_type": 4, **ALL_REALTIME}
            report.requests += 1
            resp = client.get(FRED_BASE, params={**query, "api_key": key})
            if resp.status_code != 200:
                report.errors.append(f"{series}: HTTP {resp.status_code}")  # no URL: it has the key
                continue
            observations = json.loads(resp.content)["observations"]
            url = str(httpx.URL(FRED_BASE, params=query))  # recorded without the key
            store_gz(p, book, "fred", f"fred/{k}.json.gz", k, resp.content, url)
            report.stored((p.raw / f"fred/{k}.json.gz").stat().st_size)
            days = [o["date"] for o in observations if o["value"] != "."]
            if days:
                latest = date.fromisoformat(max(days))
                report.latest_date = max(report.latest_date or latest, latest)
    return report


def fetch_cboe(p: Paths, today: date, echo=print, con=None, **_) -> FetchReport:
    report = FetchReport("cboe")
    k = f"VIX_History-{today}"
    book = Manifest(p.manifest)
    if book.find_original("cboe", k):
        return report
    url = risk_params(p)["sources"]["vix_url"]
    report.requests += 1
    resp = httpx.get(url, headers=AGENT, timeout=sources(p)["http"]["timeout_seconds"],
                     follow_redirects=True)  # fmt: skip
    resp.raise_for_status()
    lines = resp.text.strip().splitlines()
    if not lines or not lines[0].upper().startswith("DATE"):
        raise ValueError("Cboe's VIX history is not in the expected layout")
    store_gz(p, book, "cboe", f"cboe/{k}.csv.gz", k, resp.content, url)
    report.stored((p.raw / f"cboe/{k}.csv.gz").stat().st_size)
    report.latest_date = datetime.strptime(lines[-1].split(",")[0], "%m/%d/%Y").date()
    return report


def _absent(p: Paths) -> set[str]:
    path = p.finra / "short_volume" / "absent.csv"
    if not path.exists():
        return set()
    with open(path, newline="") as f:
        return {r["key"] for r in csv.DictReader(f)}


def _write_absent(p: Paths, keys: set[str]) -> None:
    path = p.finra / "short_volume" / "absent.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["key"])
        writer.writerows([k] for k in sorted(keys))


def fetch_finra(p: Paths, today: date, echo=print, con=None, from_day=None, to_day=None,
                **_) -> FetchReport:  # fmt: skip
    report = FetchReport("finra")
    rp = risk_params(p)["sources"]
    book = Manifest(p.manifest)
    stored = [datetime.strptime(e.key.split("/")[1], "%Y%m%d").date()
              for e in book.originals("finra_short")]  # fmt: skip
    start = from_day or (max(stored) + timedelta(days=1) if stored else rp["finra_short_from"])
    end = to_day or today
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    absent = _absent(p)
    rate = rp["finra_requests_per_second"]
    limiter, policy = RateLimiter(rate, rate), RetryPolicy.from_settings(sources(p)["http"])
    with httpx.Client(headers=AGENT, timeout=sources(p)["http"]["timeout_seconds"]) as client:
        for day in (d for d in days if d.weekday() < 5):
            for facility in rp["finra_short_facilities"]:
                k = f"{facility}/{day:%Y%m%d}"
                if k in absent or book.find_original("finra_short", k):
                    continue
                url = rp["finra_short_url"].format(facility=facility, day=f"{day:%Y%m%d}")
                report.requests += 1
                try:
                    resp = request_with_retry(client, "GET", url, limiter, policy)
                    missing = resp.status_code == 404
                except SecForbidden:
                    missing = True
                except RetryExhausted as e:
                    report.errors.append(f"{k}: {e}"[:200])
                    continue
                if missing:
                    if (today - day).days > FINRA_GRACE_DAYS:
                        absent.add(k)
                    continue
                if resp.status_code != 200:
                    report.errors.append(f"{k}: HTTP {resp.status_code}")
                    continue
                store_gz(p, book, "finra_short", f"finra/short_volume/{k}.txt.gz", k,
                         resp.content, url)  # fmt: skip
                report.stored((p.raw / f"finra/short_volume/{k}.txt.gz").stat().st_size)
                report.latest_date = max(report.latest_date or day, day)
    _write_absent(p, absent)
    return report
