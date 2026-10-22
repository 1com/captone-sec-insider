"""Gate G7 for the screener (plan §6.2): exclude blank-check companies (SIC 6770) and registered or
closed-end funds and BDCs (SIC 6722, 6726), which are priced off trust value or net asset value.

The plan reads the SIC code from each signal filing's header. For the July–September 2026 events
the company's current SIC from the SEC submissions API is used instead (it matches the filing-time
code for events this recent). Raw responses are cached under data/mvp/raw/ with manifest lines.
"""

import hashlib
import json
import os
from datetime import UTC, datetime

from mvp.config import MANIFEST, RAW, SENTINEL
from sentinel.config import load_secrets
from sentinel.ingest.http import (
    RateLimiter,
    RetryExhausted,
    RetryPolicy,
    make_client,
    request_with_retry,
)
from sentinel.ingest.manifest import ManifestEntry, append, read_all

FOLDER = RAW / "sec_submissions"
EXCLUDED_SIC = {"6770", "6722", "6726"}
URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def fetch(ciks, research_params, echo=print) -> dict[str, dict]:
    """Return {cik: {"sic": str, "sic_label": str}} for each CIK, downloading what is not cached."""
    FOLDER.mkdir(parents=True, exist_ok=True)
    have = {e.key for e in read_all(MANIFEST) if e.source == "sec_submissions"}
    todo = [
        c
        for c in sorted(set(ciks), key=int)
        if c not in have or not (FOLDER / f"{c}.json").exists()
    ]
    if todo:
        ops = research_params["ops"]
        secrets = load_secrets(SENTINEL.env_file)
        limiter = RateLimiter(
            ops["sec_target_requests_per_second"], ops["sec_max_requests_per_second"]
        )
        policy = RetryPolicy.from_ops(ops)
        echo(f"  SEC submissions: {len(set(ciks)) - len(todo)} cached, {len(todo)} to fetch")
        with make_client(secrets.sec_user_agent, ops["http_timeout_seconds"]) as client:
            for i, cik in enumerate(todo, start=1):
                url = URL.format(cik=int(cik))
                try:
                    resp = request_with_retry(client, "GET", url, limiter, policy)
                except RetryExhausted as e:
                    echo(f"  {cik}: {e}")
                    continue
                if resp.status_code != 200:
                    continue
                final = FOLDER / f"{cik}.json"
                part = final.with_name(final.name + ".part")
                part.write_bytes(resp.content)
                os.replace(part, final)
                append(
                    MANIFEST,
                    ManifestEntry(
                        path=final.relative_to(RAW).as_posix(),
                        source="sec_submissions",
                        key=cik,
                        role="original",
                        url=url,
                        fetched_at=datetime.now(UTC)
                        .replace(microsecond=0)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        bytes=len(resp.content),
                        sha256=hashlib.sha256(resp.content).hexdigest(),
                        http_last_modified=resp.headers.get("Last-Modified"),
                        http_etag=resp.headers.get("ETag"),
                        tool="mvp",
                    ),
                )
                if i % 50 == 0:
                    echo(f"  SEC submissions: {i}/{len(todo)}")
    out = {}
    for cik in set(ciks):
        f = FOLDER / f"{cik}.json"
        if f.exists():
            doc = json.loads(f.read_text(encoding="utf-8"))
            out[cik] = {
                "sic": str(doc.get("sic") or ""),
                "sic_label": doc.get("sicDescription") or "",
            }
    return out


def excluded(sic_info: dict) -> bool:
    """Fund, BDC or blank-check code, or no code (EDGAR leaves most funds and BDCs uncoded)."""
    return sic_info.get("sic", "") in EXCLUDED_SIC or not sic_info.get("sic")
