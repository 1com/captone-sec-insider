"""Dated snapshots of the SEC's company-ticker map (`company_tickers_exchange.json`)."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from sentinel.config import Paths
from sentinel.ingest import manifest
from sentinel.ingest.http import RateLimiter, RetryPolicy, stream_to_file
from sentinel.ingest.sec_bulk import tool_version

SOURCE = "sec_company_tickers"
PREFIX = "company_tickers_exchange_"


def fetch_company_tickers(
    paths: Paths, params: dict, client: httpx.Client, limiter: RateLimiter, policy: RetryPolicy
) -> tuple[str, Path]:
    """Store today's snapshot (once per UTC day). Returns ("stored" | "skipped", path)."""
    now = datetime.now(UTC).replace(microsecond=0)
    key = f"{now:%Y%m%d}"
    final = paths.sec_reference / f"{PREFIX}{key}.json"
    if final.exists():
        return "skipped", final
    paths.sec_reference.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + ".part")
    result = stream_to_file(client, params["ops"]["sec_company_tickers_url"], part, limiter, policy)
    try:
        doc = json.loads(part.read_text(encoding="utf-8"))
        if doc.get("fields") != ["cik", "name", "ticker", "exchange"] or not doc.get("data"):
            raise ValueError("unexpected layout")
    except (ValueError, AttributeError) as e:
        part.unlink(missing_ok=True)
        raise ValueError(f"SEC ticker map is not in the expected format: {e}") from e
    os.replace(part, final)
    os.chmod(final, 0o444)
    manifest.append(
        paths.manifest,
        manifest.ManifestEntry(
            path=final.relative_to(paths.data_raw).as_posix(),
            source=SOURCE,
            key=key,
            role="original",
            url=result.url,
            fetched_at=now.isoformat().replace("+00:00", "Z"),
            bytes=result.bytes,
            sha256=result.sha256,
            http_last_modified=result.last_modified,
            http_etag=result.etag,
            tool=tool_version(),
        ),
    )
    return "stored", final


def latest_snapshot(paths: Paths) -> Path | None:
    snapshots = sorted(paths.sec_reference.glob(f"{PREFIX}*.json"))
    return snapshots[-1] if snapshots else None


def load_snapshot(path: Path) -> dict[str, list[tuple[str, str | None]]]:
    """CIK (no zero padding) → [(ticker, exchange), ...]."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[tuple[str, str | None]]] = {}
    for cik, _name, ticker, exchange in doc["data"]:
        out.setdefault(str(int(cik)), []).append((ticker, exchange))
    return out
