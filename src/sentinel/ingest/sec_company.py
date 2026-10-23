"""SEC bulk company data: `companyfacts.zip` (XBRL facts) and `submissions.zip` (filing histories)
(feature 004, research R9).

Two downloads replace thousands of per-company requests. Both archives are stored as received under
`data/raw/sec/company/` with manifest lines; readers open one company's JSON at a time, so memory
stays at one company's file.
"""

import json
import os
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime

from sentinel.config import Paths
from sentinel.ingest import manifest
from sentinel.ingest.http import RateLimiter, RetryPolicy, stream_to_file

SOURCE = "sec_company"
ARCHIVES = {"companyfacts": "sec_companyfacts_url", "submissions": "sec_submissions_url"}


def archive_path(paths: Paths, name: str):
    return paths.sec_company / f"{name}.zip"


def fetch(
    paths: Paths, params: dict, client, limiter: RateLimiter, policy: RetryPolicy, echo=print
):
    """Download both archives unless already stored; returns {name: 'stored' | 'kept'}."""
    book = manifest.Manifest(paths.manifest)
    paths.sec_company.mkdir(parents=True, exist_ok=True)
    done = {}
    for name, url_key in ARCHIVES.items():
        final = archive_path(paths, name)
        if book.find_original(SOURCE, name) and final.exists():
            done[name] = "kept"
            continue
        url = params["ops"][url_key]
        echo(f"sec-company: downloading {name}.zip")
        part = final.with_name(final.name + ".part")
        result = stream_to_file(client, url, part, limiter, policy)
        os.replace(part, final)
        os.chmod(final, 0o444)
        book.add(
            manifest.ManifestEntry(
                path=final.relative_to(paths.data_raw).as_posix(),
                source=SOURCE,
                key=name,
                role="original",
                url=result.url,
                fetched_at=datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                bytes=result.bytes,
                sha256=result.sha256,
                http_last_modified=result.last_modified,
                http_etag=result.etag,
                tool="sentinel",
            )
        )
        echo(f"  {result.bytes / 1e9:.2f} GB stored")
        done[name] = "stored"
    return done


def member(cik: str) -> str:
    return f"CIK{int(cik):010d}.json"


def iter_submissions(zf: zipfile.ZipFile, ciks) -> Iterator[tuple[str, dict, list[dict]]]:
    """(cik, the company's document, its filing arrays: `recent` then each extra page)."""
    names = set(zf.namelist())
    for cik in sorted(ciks, key=int):
        if member(cik) not in names:
            continue
        doc = json.loads(zf.read(member(cik)))
        filings = doc.get("filings", {})
        pages = [filings.get("recent", {})]
        for extra in filings.get("files", []):
            if extra.get("name") in names:
                pages.append(json.loads(zf.read(extra["name"])))
        yield cik, doc, pages


def read_companyfacts(zf: zipfile.ZipFile, cik: str) -> dict | None:
    try:
        return json.loads(zf.read(member(cik)))
    except KeyError:
        return None
