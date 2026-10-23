import hashlib
import json

import pytest

from sentinel.ingest.manifest import (
    FetchLock,
    FetchLocked,
    ManifestEntry,
    ManifestError,
    append,
    find_original,
    read_all,
    verify,
)

FIELDS = [
    "path",
    "source",
    "key",
    "role",
    "url",
    "fetched_at",
    "bytes",
    "sha256",
    "http_last_modified",
    "http_etag",
    "tool",
]


def _store(tmp_data, rel, content: bytes, key, role="original"):
    f = tmp_data.data_raw / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content)
    entry = ManifestEntry(
        path=rel,
        source="sec_insider_bulk",
        key=key,
        role=role,
        url=f"https://x/{rel}",
        fetched_at="2026-10-22T11:11:04Z",
        bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        http_last_modified=None,
        http_etag=None,
        tool="sentinel 0.1.0+test",
    )
    append(tmp_data.manifest, entry)
    return f, entry


def test_append_writes_one_line_with_exact_fields(tmp_data):
    _store(tmp_data, "sec/insider/2019q1_form345.zip", b"abc", "2019q1")
    lines = tmp_data.manifest.read_text().splitlines()
    assert len(lines) == 1
    assert list(json.loads(lines[0])) == FIELDS
    assert read_all(tmp_data.manifest)[0].key == "2019q1"
    assert find_original(tmp_data.manifest, "sec_insider_bulk", "2019q1").bytes == 3


def test_second_original_for_same_key_is_rejected(tmp_data):
    _store(tmp_data, "sec/insider/2019q1_form345.zip", b"abc", "2019q1")
    with pytest.raises(ManifestError):
        _store(tmp_data, "sec/insider/other.zip", b"def", "2019q1")


def test_duplicate_path_is_rejected(tmp_data):
    _store(tmp_data, "sec/insider/2019q1_form345.zip", b"abc", "2019q1")
    with pytest.raises(ManifestError):
        _store(tmp_data, "sec/insider/2019q1_form345.zip", b"abc", "2019q2", role="refetch")


def test_verify_classifies_files(tmp_data):
    _store(tmp_data, "sec/insider/a.zip", b"aaa", "2019q1")
    changed, _ = _store(tmp_data, "sec/insider/b.zip", b"bbb", "2019q2")
    gone, _ = _store(tmp_data, "sec/insider/c.zip", b"ccc", "2019q3")
    changed.chmod(0o644)
    changed.write_bytes(b"tampered")
    gone.unlink()
    (tmp_data.sec_insider / "stray.zip").write_bytes(b"?")
    (tmp_data.sec_insider / "d.zip.part").write_bytes(b"partial")
    tmp_data.lock.write_text("")

    report = verify(tmp_data, prefix="sec/")
    assert report.ok == ["sec/insider/a.zip"]
    assert report.mismatch == ["sec/insider/b.zip"]
    assert report.missing == ["sec/insider/c.zip"]
    assert report.unrecorded == ["sec/insider/stray.zip"]


def test_second_lock_fails(tmp_data):
    tmp_data.data_raw.mkdir(parents=True)
    with (
        FetchLock(tmp_data.lock),
        pytest.raises(FetchLocked, match="another fetch is running"),
        FetchLock(tmp_data.lock),
    ):
        pass
    with FetchLock(tmp_data.lock):
        pass  # released after the first context ends


def test_manifest_never_holds_secrets(tmp_data):
    _store(tmp_data, "sec/insider/a.zip", b"aaa", "2019q1")
    text = tmp_data.manifest.read_text()
    assert "test@example.com" not in text
    assert "tiingo-secret-123" not in text
