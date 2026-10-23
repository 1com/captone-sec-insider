"""The append-only raw-data manifest, `data/raw/manifest.jsonl`.

One JSON line per stored file, written only after the file is complete and read-only. Lines are
never edited. Contract: specs/001-skeleton-sec-ingest/contracts/raw-manifest.md
"""

import fcntl
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sentinel.config import Paths

CHUNK = 1 << 20


class ManifestError(Exception):
    pass


class FetchLocked(Exception):
    pass


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    source: str
    key: str
    role: str
    url: str
    fetched_at: str
    bytes: int
    sha256: str
    http_last_modified: str | None
    http_etag: str | None
    tool: str


def read_all(manifest_path: Path) -> list[ManifestEntry]:
    if not manifest_path.exists():
        return []
    with open(manifest_path, encoding="utf-8") as f:
        return [ManifestEntry(**json.loads(line)) for line in f if line.strip()]


def find_original(manifest_path: Path, source: str, key: str) -> ManifestEntry | None:
    return next(
        (
            e
            for e in read_all(manifest_path)
            if e.source == source and e.key == key and e.role == "original"
        ),
        None,
    )


def append(manifest_path: Path, entry: ManifestEntry) -> None:
    existing = read_all(manifest_path)
    if any(e.path == entry.path for e in existing):
        raise ManifestError(f"manifest already lists {entry.path}")
    if entry.role == "original" and any(
        e.source == entry.source and e.key == entry.key and e.role == "original" for e in existing
    ):
        raise ManifestError(f"manifest already has an original for {entry.source}/{entry.key}")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class VerifyReport:
    ok: list[str] = field(default_factory=list)
    mismatch: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unrecorded: list[str] = field(default_factory=list)


def verify(paths: Paths, prefix: str = "sec/") -> VerifyReport:
    """Re-hash every manifest file under `prefix` and list files the manifest does not know."""
    report = VerifyReport()
    listed = set()
    for entry in read_all(paths.manifest):
        if not entry.path.startswith(prefix):
            continue
        listed.add(entry.path)
        file = paths.data_raw / entry.path
        if not file.exists():
            report.missing.append(entry.path)
        elif sha256_file(file) != entry.sha256:
            report.mismatch.append(entry.path)
        else:
            report.ok.append(entry.path)
    root = paths.data_raw / prefix
    if root.exists():
        for file in sorted(root.rglob("*")):
            rel = file.relative_to(paths.data_raw).as_posix()
            if file.is_file() and not file.name.endswith(".part") and rel not in listed:
                report.unrecorded.append(rel)
    return report


class FetchLock:
    """Stops two fetch commands writing to data/raw/ at once."""

    def __init__(self, lock_path: Path):
        self._path = lock_path
        self._file = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "w")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            self._file.close()
            raise FetchLocked("another fetch is running") from e
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._file, fcntl.LOCK_UN)
        self._file.close()
