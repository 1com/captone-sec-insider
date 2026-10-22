"""Step 1: download the quarterly SEC Insider Transactions data sets.

Per quarter: missing → downloading (.part, hashed) → validating (zip CRC + required tables) →
stored (renamed, read-only, manifest line). A failure leaves no file under the final name, and a
stored file is never overwritten. See specs/001-skeleton-sec-ingest/data-model.md §2.
"""

import logging
import os
import re
import subprocess
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

from sentinel import __version__
from sentinel.config import Paths, registered_value
from sentinel.ingest import manifest
from sentinel.ingest.http import (
    RateLimiter,
    RetryExhausted,
    RetryPolicy,
    request_with_retry,
    stream_to_file,
)

log = logging.getLogger(__name__)

SOURCE = "sec_insider_bulk"
SEC_BASE = "https://www.sec.gov"
QUARTER_RE = re.compile(r"^(\d{4})q([1-4])$")
LINK_RE = re.compile(r'href="([^"]*?(\d{4}q[1-4])_form345\.zip)"')


def quarters_in_range(start: str, end: str) -> list[str]:
    def parse(key):
        m = QUARTER_RE.match(key)
        if not m:
            raise ValueError(f"not a quarter key: {key!r} (expected e.g. 2019q1)")
        return int(m[1]), int(m[2])

    (y, q), last = parse(start), parse(end)
    keys = []
    while (y, q) <= last:
        keys.append(f"{y}q{q}")
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return keys


def archive_name(key: str) -> str:
    return f"{key}_form345.zip"


def discover_urls(
    client: httpx.Client,
    limiter: RateLimiter,
    policy: RetryPolicy,
    keys: list[str],
    landing_page: str,
    patterns: list[str],
) -> dict[str, str]:
    """Read the links on the SEC landing page; HEAD the known folders for any quarter not listed."""
    found: dict[str, str] = {}
    try:
        resp = request_with_retry(client, "GET", landing_page, limiter, policy)
        if resp.status_code == 200:
            for href, key in LINK_RE.findall(resp.text):
                found.setdefault(key, urljoin(SEC_BASE, href))
        else:
            log.warning("landing page returned HTTP %d; trying known folders", resp.status_code)
    except RetryExhausted as e:
        log.warning("landing page unavailable (%s); trying known folders", e)

    urls = {}
    for key in keys:
        if key in found:
            urls[key] = found[key]
            continue
        for pattern in patterns:
            url = pattern.format(key=key)
            try:
                if request_with_retry(client, "HEAD", url, limiter, policy).status_code == 200:
                    urls[key] = url
                    break
            except RetryExhausted as e:
                log.warning("HEAD %s failed: %s", url, e)
    return urls


def validate_archive(path: Path, required: list[str]) -> str | None:
    """None if the zip is intact and has every required table, otherwise the reason."""
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad is not None:
                return f"corrupt member {bad}"
            names = set(zf.namelist())
    except (zipfile.BadZipFile, OSError) as e:
        return f"not a readable zip ({e})"
    missing = [t for t in required if f"{t}.tsv" not in names]
    return f"missing table(s): {', '.join(missing)}" if missing else None


@dataclass
class QuarterResult:
    key: str
    status: str  # stored | skipped | failed | planned
    reason: str = ""
    bytes: int = 0
    url: str = ""


@dataclass
class FetchSummary:
    results: list[QuarterResult] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(r.status == status for r in self.results)

    @property
    def bytes(self) -> int:
        return sum(r.bytes for r in self.results if r.status == "stored")


def tool_version() -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        commit = "unknown"
    return f"sentinel {__version__}+{commit}"


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def fetch_quarters(
    paths: Paths,
    params: dict,
    client: httpx.Client,
    limiter: RateLimiter,
    policy: RetryPolicy,
    *,
    keys: list[str] | None = None,
    refetch: str | None = None,
    dry_run: bool = False,
    on_result: Callable[[QuarterResult], None] | None = None,
) -> FetchSummary:
    period = registered_value(params, "insider_data_period")
    all_keys = quarters_in_range(str(period["start"]), str(period["end"]))
    for key in [*(keys or []), *([refetch] if refetch else [])]:
        if key not in all_keys:
            raise ValueError(f"quarter {key} is outside {period['start']}–{period['end']}")
    ops = params["ops"]
    summary = FetchSummary()

    def report(result: QuarterResult) -> None:
        summary.results.append(result)
        if on_result:
            on_result(result)

    paths.sec_insider.mkdir(parents=True, exist_ok=True)
    for stale in paths.sec_insider.glob("*.part"):
        stale.unlink()

    targets = [refetch] if refetch else (keys or all_keys)
    to_download = []
    for key in targets:
        final = paths.sec_insider / archive_name(key)
        original = manifest.find_original(paths.manifest, SOURCE, key)
        if refetch:
            if original is None:
                report(QuarterResult(key, "failed", "nothing stored to refetch"))
            else:
                to_download.append(key)
        elif original is None and final.exists():
            report(QuarterResult(key, "failed", "unrecorded file present; left alone"))
        elif original is None:
            to_download.append(key)
        elif not final.exists():
            report(QuarterResult(key, "failed", "manifest lists it but the file is missing"))
        elif manifest.sha256_file(final) == original.sha256:
            report(QuarterResult(key, "skipped", "verified"))
        else:
            report(QuarterResult(key, "failed", "stored file differs from manifest"))
    if not to_download:
        summary.results.sort(key=lambda r: r.key)
        return summary

    urls = discover_urls(
        client, limiter, policy, to_download, ops["sec_landing_page"], ops["sec_folder_patterns"]
    )
    tool = tool_version()
    for key in to_download:
        url = urls.get(key)
        if url is None:
            report(QuarterResult(key, "failed", "not found in either SEC folder"))
            continue
        if dry_run:
            report(QuarterResult(key, "planned", url=url))
            continue
        report(
            _download_one(paths, key, url, refetch is not None, tool, ops, client, limiter, policy)
        )
    summary.results.sort(key=lambda r: r.key)
    return summary


def _download_one(paths, key, url, is_refetch, tool, ops, client, limiter, policy) -> QuarterResult:
    stamp = _utc_now()
    name = archive_name(key)
    if is_refetch:
        name = name.replace(".zip", f"__refetch_{stamp:%Y%m%dT%H%M%SZ}.zip")
    final = paths.sec_insider / name
    part = final.with_name(final.name + ".part")
    try:
        result = stream_to_file(client, url, part, limiter, policy)
    except (RetryExhausted, httpx.HTTPStatusError, OSError) as e:
        return QuarterResult(key, "failed", str(e), url=url)

    problem = validate_archive(part, ops["required_archive_tables"])
    if problem:
        part.unlink(missing_ok=True)
        return QuarterResult(key, "failed", problem, url=url)
    os.replace(part, final)
    os.chmod(final, 0o444)
    manifest.append(
        paths.manifest,
        manifest.ManifestEntry(
            path=final.relative_to(paths.data_raw).as_posix(),
            source=SOURCE,
            key=key,
            role="refetch" if is_refetch else "original",
            url=result.url,
            fetched_at=_utc_now().isoformat().replace("+00:00", "Z"),
            bytes=result.bytes,
            sha256=result.sha256,
            http_last_modified=result.last_modified,
            http_etag=result.etag,
            tool=tool,
        ),
    )
    return QuarterResult(key, "stored", bytes=result.bytes, url=url)
