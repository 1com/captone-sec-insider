"""SEC (EDGAR) downloads (specs/001-daily-data-refresh, research R2–R5).

- `sec-tickers`: the SEC's company–ticker list, once a day.
- `sec-daily`: per filing day, the master index; the headers of filings whose details are used
  (`sec.detail_forms`); the financial values of periodic-report filers; the filing histories of
  CIKs not seen before.
- `form4`: per filing day, every Form 3, 4 and 5 and amendment as its full submission.
- `sec-bulk`: new copies of the bulk filing histories and financial values.

Every SEC request in the process shares one rate limiter (`sec.document_requests_per_second`,
never above 10 a second) and carries the contact from `.env`.
"""

import contextlib
import csv
import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx

from sentinel import db
from sentinel.config import ConfigError, Paths, secrets, sources
from sentinel.raw import FetchReport
from sentinel.raw.http import (
    RateLimiter,
    RetryPolicy,
    is_missing,
    make_client,
    request_with_retry,
    stream_to_file,
)
from sentinel.raw.manifest import Manifest, ManifestEntry, read_stored, store_bytes, store_gz
from sentinel.staging.sec_filings import COMPANY_FORMS

_LIMITER: RateLimiter | None = None
_LIMITER_LOCK = threading.Lock()
INDEX_GRACE_DAYS = 4  # an index still missing this many days later: no filings that day (holiday)
FIRST_DAILY_DAY = date(2026, 10, 1)  # the day after the last quarterly Form 4 data set (2026q3)


def shared_limiter(settings: dict) -> RateLimiter:
    """The one SEC rate limiter of this process, so sources fetched in parallel share the rate."""
    global _LIMITER
    with _LIMITER_LOCK:
        if _LIMITER is None:
            sec = settings["sec"]
            _LIMITER = RateLimiter(sec["document_requests_per_second"],
                                   sec["max_requests_per_second"])  # fmt: skip
        return _LIMITER


def sec_client(p: Paths) -> tuple[httpx.Client, RateLimiter, RetryPolicy, dict]:
    """(client with the contact User-Agent, the shared limiter, the retry policy, the settings)."""
    settings = sources(p)
    agent = secrets(p).sec_user_agent
    if not agent:
        raise ConfigError("SEC_USER_AGENT missing in .env: the SEC requires a contact")
    client = make_client(agent, settings["http"]["timeout_seconds"])
    return client, shared_limiter(settings), RetryPolicy.from_settings(settings["http"]), settings


def filing_days(start: date, end: date) -> list[date]:
    """Weekdays from `start` to `end`, both included (EDGAR files nothing at weekends)."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5]  # fmt: skip


def index_url(settings: dict, day: date) -> str:
    return settings["sec"]["daily_index_url"].format(
        year=day.year, quarter=(day.month - 1) // 3 + 1, day=f"{day:%Y%m%d}"
    )


@dataclass(frozen=True)
class IndexRow:
    cik: str
    company: str
    form: str
    filed: date
    file_name: str  # edgar/data/<cik>/<accession>.txt

    @property
    def accession(self) -> str:
        return self.file_name.rsplit("/", 1)[1].removesuffix(".txt")


def parse_index(text: str) -> list[IndexRow]:
    """The rows of a master index (`CIK|Company Name|Form Type|Date Filed|File Name`)."""
    rows, started = [], False
    for line in text.splitlines():
        if line.startswith("-----"):
            started = True
            continue
        parts = line.split("|")
        if started and len(parts) == 5:
            cik, company, form, filed, file_name = parts
            rows.append(IndexRow(str(int(cik)), company, form,
                                 datetime.strptime(filed, "%Y%m%d").date(), file_name))  # fmt: skip
    return rows


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextlib.contextmanager
def _reader(p: Paths, con):
    """The caller's connection, or a read-only one of the build database."""
    if con is not None:
        yield con
        return
    if not p.build_db.exists():
        raise db.MissingInput("the build database is missing: run `sentinel build staging` first")
    reader = db.connect(p, read_only=True)
    try:
        yield reader
    finally:
        reader.close()


class _Sec:
    """One fetch run's SEC session: client, shared limiter, retry policy, manifest, report."""

    def __init__(self, p: Paths, report: FetchReport):
        self.p, self.report = p, report
        self.client, self.limiter, self.policy, self.settings = sec_client(p)
        self.book = Manifest(p.manifest)

    def get(self, url: str, allow_missing: bool = False) -> httpx.Response | None:
        """The answer, or None for a file the store does not have (with `allow_missing`)."""
        self.report.requests += 1
        resp = request_with_retry(self.client, "GET", url, self.limiter, self.policy,
                                  allow_missing=allow_missing)  # fmt: skip
        if allow_missing and is_missing(resp):
            return None
        resp.raise_for_status()
        return resp

    def store(self, source: str, rel: str, key: str, data: bytes, url: str, gz: bool) -> None:
        (store_gz if gz else store_bytes)(self.p, self.book, source, rel, key, data, url)
        self.report.stored((self.p.raw / rel).stat().st_size)

    def close(self) -> None:
        self.client.close()


def fetch_tickers(p: Paths, today: date, echo=print, con=None, **_) -> FetchReport:
    """Today's SEC company–ticker list (once a day), checked for its layout before storing."""
    report = FetchReport("sec-tickers")
    key = f"{today:%Y%m%d}"
    sec = _Sec(p, report)
    try:
        if sec.book.find_original("sec_company_tickers", key):
            return report
        url = sec.settings["sec"]["company_tickers_url"]
        data = sec.get(url).content
        doc = json.loads(data)
        if doc.get("fields") != ["cik", "name", "ticker", "exchange"] or not doc.get("data"):
            raise ValueError("the SEC ticker list is not in the expected layout")
        sec.store("sec_company_tickers", f"sec/reference/company_tickers_exchange_{key}.json", key,
                  data, url, gz=False)  # fmt: skip
        report.latest_date = today
        echo(f"  sec-tickers: {len(doc['data']):,} tickers")
        return report
    finally:
        sec.close()


def _cursor(p: Paths, name: str) -> date | None:
    """The last filing day a fetcher (`sec-daily`, `form4`) finished, kept beside the indexes."""
    path = p.sec_index / f"done-{name}.txt"
    return date.fromisoformat(path.read_text().strip()) if path.exists() else None


def _set_cursor(p: Paths, name: str, day: date) -> None:
    p.sec_index.mkdir(parents=True, exist_ok=True)
    path = p.sec_index / f"done-{name}.txt"
    part = path.with_name(path.name + ".part")
    part.write_text(f"{day.isoformat()}\n")
    os.replace(part, path)


def _fetched_day(entry: ManifestEntry) -> date:
    return datetime.fromisoformat(entry.fetched_at.replace("Z", "+00:00")).date()


def _absent_days(p: Paths) -> set[date]:
    path = p.sec_index / "absent.csv"
    if not path.exists():
        return set()
    with open(path, newline="") as f:
        return {date.fromisoformat(r["day"]) for r in csv.DictReader(f)}


def _write_absent(p: Paths, days: set[date]) -> None:
    p.sec_index.mkdir(parents=True, exist_ok=True)
    with open(p.sec_index / "absent.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["day"])
        writer.writerows([d.isoformat()] for d in sorted(days))


def _index(sec: _Sec, day: date) -> list[IndexRow] | None:
    """The day's master index (stored on first fetch), or None when not published."""
    key = f"master/{day:%Y%m%d}"
    entry = sec.book.find_original("sec_index", key)
    if entry is not None:
        return parse_index(read_stored(sec.p, entry).decode("latin-1"))
    url = index_url(sec.settings, day)
    resp = sec.get(url, allow_missing=True)
    if resp is None:
        return None
    sec.store("sec_index", f"sec/index/{day:%Y}/master.{day:%Y%m%d}.idx.gz", key, resp.content,
              url, gz=True)  # fmt: skip
    return parse_index(resp.content.decode("latin-1"))


def index_days(p: Paths, today: date, name: str, start: date, from_day: date | None,
               to_day: date | None) -> list[date]:  # fmt: skip
    """The filing days fetcher `name` still has to do: from `from_day`, else the day after its
    cursor, else `start`; to `to_day`, else yesterday; weekdays without known holidays."""
    done = _cursor(p, name)
    first = from_day or (done + timedelta(days=1) if done else start)
    last = to_day or today - timedelta(days=1)
    absent = _absent_days(p)
    return [d for d in filing_days(first, last) if d not in absent]


def _each_index(sec: _Sec, days: list[date], today: date, echo, name: str):
    """(day, rows) for each published index in `days`, in order, moving fetcher `name`'s cursor
    after each day is done. A missing index older than `INDEX_GRACE_DAYS` is recorded as a day
    without filings (a holiday); a newer one is not published yet and ends the run."""
    absent = _absent_days(sec.p)
    for day in days:
        rows = _index(sec, day)
        if rows is None:
            if (today - day).days > INDEX_GRACE_DAYS:
                absent.add(day)
                _write_absent(sec.p, absent)
                continue
            echo(f"  {day}: index not published yet")
            break
        sec.report.latest_date = day
        yield day, rows
        _set_cursor(sec.p, name, day)


def daily_start(book: Manifest) -> date:
    """Where `sec-daily` starts without a cursor: the day the newest bulk filing history was
    fetched (its filings up to then are in the base)."""
    bulk = [e for e in book.originals("sec_company") if e.key.startswith("submissions")]
    return max(_fetched_day(e) for e in bulk) if bulk else FIRST_DAILY_DAY


def form4_start(book: Manifest) -> date:
    """Where `form4` starts without a cursor: the day after the newest quarterly data set."""
    quarters = sorted(e.key for e in book.originals("sec_insider_bulk"))
    if not quarters:
        return FIRST_DAILY_DAY
    year, q = int(quarters[-1][:4]), int(quarters[-1][-1])
    return date(year + q // 4, q % 4 * 3 + 1, 1)


def _header_urls(settings: dict, row: IndexRow) -> list[str]:
    acc = row.accession
    fill = {"cik": row.file_name.split("/")[2], "acc_nodash": acc.replace("-", ""), "acc": acc}
    return [settings["sec"]["headers_url_pattern"].format(**fill),
            settings["sec"]["headers_fallback_url_pattern"].format(**fill)]  # fmt: skip


def fetch_daily(p: Paths, today: date, echo=print, con=None, from_day=None, to_day=None,
                **_) -> FetchReport:  # fmt: skip
    """For each filing day: the index; headers of company filings in `sec.detail_forms`; the
    financial values (`companyfacts`) of `sec.periodic_forms` filers; the filing history of each
    CIK not yet known that filed a company form (research R2, R4, R5)."""
    report = FetchReport("sec-daily")
    with _reader(p, con) as reader:
        db.require(reader, ["stg_sec_filings.filer"], "sentinel fetch sec-daily")
        known = dict(reader.execute("select cik, is_company from stg_sec_filings.filer").fetchall())
    sec = _Sec(p, report)
    try:
        s = sec.settings["sec"]
        detail, periodic = set(s["detail_forms"]), set(s["periodic_forms"])
        asked = {e.key.split("/")[0] for e in sec.book.originals("sec_submissions_cik")}
        days = index_days(p, today, "sec-daily", daily_start(sec.book), from_day, to_day)
        for day, rows in _each_index(sec, days, today, echo, "sec-daily"):
            # a known company, or a CIK first seen today filing a company's form
            company = [
                r for r in rows
                if known.get(r.cik) or (r.cik not in known and r.form in COMPANY_FORMS)
            ]  # fmt: skip
            details = {r.accession: r for r in company if r.form in detail}
            for r in sorted(details.values(), key=lambda r: r.accession):
                if sec.book.find_original("sec_filing_header", r.accession):
                    continue
                for url in _header_urls(sec.settings, r):
                    resp = sec.get(url, allow_missing=True)
                    if resp is not None:
                        sec.store("sec_filing_header", f"sec/headers/{day:%Y}/{r.accession}.txt",
                                  r.accession, resp.content, url, gz=False)  # fmt: skip
                        break
            for cik in sorted({r.cik for r in company if r.form in periodic}, key=int):
                key = f"{cik}/{today}"
                if sec.book.find_original("sec_companyfacts_cik", key):
                    continue
                url = s["companyfacts_cik_url"].format(cik10=f"{int(cik):010d}")
                resp = sec.get(url, allow_missing=True)
                if resp is not None:
                    sec.store("sec_companyfacts_cik",
                              f"sec/companyfacts/{today}/CIK{int(cik):010d}.json.gz", key,
                              resp.content, url, gz=True)  # fmt: skip
            for cik in sorted({r.cik for r in company if r.cik not in known} - asked, key=int):
                url = s["submissions_cik_url"].format(cik10=f"{int(cik):010d}")
                resp = sec.get(url, allow_missing=True)
                asked.add(cik)
                if resp is not None:
                    sec.store("sec_submissions_cik",
                              f"sec/submissions/{today}/CIK{int(cik):010d}.json.gz",
                              f"{cik}/{today}", resp.content, url, gz=True)  # fmt: skip
            echo(f"  {day}: {len(rows):,} filings indexed, {report.files_stored:,} files so far")
        return report
    finally:
        sec.close()


def fetch_bulk(p: Paths, today: date, echo=print, con=None, **_) -> FetchReport:
    """New copies of `submissions.zip` and `companyfacts.zip` (a new base), streamed to disk."""
    report = FetchReport("sec-bulk")
    sec = _Sec(p, report)
    try:
        for name in ("submissions", "companyfacts"):
            key = f"{name}/{today}"
            if sec.book.find_original("sec_company", key):
                continue
            url = sec.settings["sec"][f"{name}_url"]
            final = p.sec_company / f"{today}" / f"{name}.zip"
            final.parent.mkdir(parents=True, exist_ok=True)
            part = final.with_name(final.name + ".part")
            echo(f"  sec-bulk: downloading {name}.zip")
            report.requests += 1
            result = stream_to_file(sec.client, url, part, sec.limiter, sec.policy)
            os.replace(part, final)
            os.chmod(final, 0o444)
            sec.book.add(ManifestEntry(
                path=final.relative_to(p.raw).as_posix(), source="sec_company", key=key,
                role="original", url=result.url, fetched_at=_now(), bytes=result.bytes,
                sha256=result.sha256, http_last_modified=result.last_modified,
                http_etag=result.etag, tool="sentinel"))  # fmt: skip
            report.stored(result.bytes)
            report.latest_date = today
        return report
    finally:
        sec.close()
