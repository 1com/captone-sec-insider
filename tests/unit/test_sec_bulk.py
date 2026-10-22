import copy
import hashlib
import stat
from pathlib import Path

import httpx
import pytest
import respx

from sentinel.ingest.http import RateLimiter, RetryPolicy, SecForbidden, make_client
from sentinel.ingest.manifest import find_original, read_all
from sentinel.ingest.sec_bulk import (
    discover_urls,
    fetch_quarters,
    quarters_in_range,
    validate_archive,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
LANDING = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
OLD = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"
NEW = "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets"
REQUIRED = ["SUBMISSION", "REPORTINGOWNER", "NONDERIV_TRANS", "FOOTNOTES"]


@pytest.fixture
def small_params(params):
    p = copy.deepcopy(params)
    p["registered"]["insider_data_period"]["value"] = {"start": "2019q1", "end": "2019q2"}
    return p


@pytest.fixture
def net():
    sleeps = []
    return {
        "client": make_client("Test User test@example.com", 5),
        "limiter": RateLimiter(5, 10, clock=lambda: 0.0, sleep=lambda s: None),
        "policy": RetryPolicy(3, 0.0, 0.0, sleep=sleeps.append),
    }


def _mock_site(zip_bytes: dict[str, bytes]):
    """Landing page lists 2019q1 (old folder); 2019q2 exists only in the new folder."""
    respx.get(LANDING).mock(
        return_value=httpx.Response(200, text=(FIXTURES / "sec_landing.html").read_text())
    )
    respx.head(f"{OLD}/2019q2_form345.zip").mock(return_value=httpx.Response(404))
    respx.head(f"{NEW}/2019q2_form345.zip").mock(return_value=httpx.Response(200))
    for key, body in zip_bytes.items():
        folder = OLD if key == "2019q1" else NEW
        respx.get(f"{folder}/{key}_form345.zip").mock(
            return_value=httpx.Response(200, content=body)
        )


def _fetch(tmp_data, params, net, **kw):
    return fetch_quarters(tmp_data, params, net["client"], net["limiter"], net["policy"], **kw)


def test_quarters_in_range():
    keys = quarters_in_range("2006q1", "2026q3")
    assert len(keys) == 83
    assert keys[0] == "2006q1" and keys[-1] == "2026q3"


@respx.mock
def test_discover_maps_both_layouts_and_falls_back(params, net):
    _mock_site({})
    respx.head(f"{OLD}/2023q2_form345.zip").mock(return_value=httpx.Response(200))
    urls = discover_urls(
        net["client"],
        net["limiter"],
        net["policy"],
        ["2019q1", "2026q3", "2019q2", "2023q2"],
        LANDING,
        params["ops"]["sec_folder_patterns"],
    )
    assert urls == {
        "2019q1": f"{OLD}/2019q1_form345.zip",
        "2026q3": f"{NEW}/2026q3_form345.zip",
        "2019q2": f"{NEW}/2019q2_form345.zip",
        "2023q2": f"{OLD}/2023q2_form345.zip",
    }


def test_validate_archive(tmp_path, quarter_zip):
    good = tmp_path / "good.zip"
    good.write_bytes(quarter_zip())
    assert validate_archive(good, REQUIRED) is None
    missing = tmp_path / "missing.zip"
    missing.write_bytes(quarter_zip(omit={"FOOTNOTES"}))
    assert "FOOTNOTES" in validate_archive(missing, REQUIRED)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    assert validate_archive(junk, REQUIRED) is not None


@respx.mock
def test_successful_fetch_stores_read_only_with_manifest(tmp_data, small_params, net, quarter_zip):
    body = quarter_zip()
    _mock_site({"2019q1": body, "2019q2": body})
    summary = _fetch(tmp_data, small_params, net)
    assert [r.status for r in summary.results] == ["stored", "stored"]
    f = tmp_data.sec_insider / "2019q1_form345.zip"
    assert f.read_bytes() == body
    assert stat.S_IMODE(f.stat().st_mode) == 0o444
    entry = find_original(tmp_data.manifest, "sec_insider_bulk", "2019q1")
    assert entry.sha256 == hashlib.sha256(body).hexdigest()
    assert entry.path == "sec/insider/2019q1_form345.zip"
    assert not list(tmp_data.sec_insider.glob("*.part"))


@respx.mock
def test_bad_archives_fail_without_leaving_files(tmp_data, small_params, net, quarter_zip):
    _mock_site({"2019q1": b"corrupt", "2019q2": quarter_zip(omit={"FOOTNOTES"})})
    summary = _fetch(tmp_data, small_params, net)
    assert [r.status for r in summary.results] == ["failed", "failed"]
    assert not list(tmp_data.sec_insider.iterdir())
    assert read_all(tmp_data.manifest) == []


class _Broken(httpx.SyncByteStream):
    def __iter__(self):
        yield b"PK"
        raise httpx.ReadError("reset")


@respx.mock
def test_interrupted_quarter_resumes_and_stale_part_is_removed(
    tmp_data, small_params, net, quarter_zip
):
    body = quarter_zip()
    _mock_site({"2019q2": body})
    respx.get(f"{OLD}/2019q1_form345.zip").mock(return_value=httpx.Response(200, stream=_Broken()))
    first = _fetch(tmp_data, small_params, net)
    assert [r.status for r in first.results] == ["failed", "stored"]
    assert not (tmp_data.sec_insider / "2019q1_form345.zip").exists()

    stale = tmp_data.sec_insider / "2019q1_form345.zip.part"
    stale.write_bytes(b"left over")
    respx.get(f"{OLD}/2019q1_form345.zip").mock(return_value=httpx.Response(200, content=body))
    second = _fetch(tmp_data, small_params, net)
    assert [r.status for r in second.results] == ["stored", "skipped"]
    assert not stale.exists()


@respx.mock
def test_rerun_makes_no_requests(tmp_data, small_params, net, quarter_zip):
    _mock_site({"2019q1": quarter_zip(), "2019q2": quarter_zip()})
    _fetch(tmp_data, small_params, net)
    calls_before = len(respx.calls)
    summary = _fetch(tmp_data, small_params, net)
    assert [r.status for r in summary.results] == ["skipped", "skipped"]
    assert len(respx.calls) == calls_before


@respx.mock
def test_altered_file_is_reported_not_overwritten(tmp_data, small_params, net, quarter_zip):
    _mock_site({"2019q1": quarter_zip(), "2019q2": quarter_zip()})
    _fetch(tmp_data, small_params, net)
    f = tmp_data.sec_insider / "2019q1_form345.zip"
    f.chmod(0o644)
    f.write_bytes(b"tampered")
    summary = _fetch(tmp_data, small_params, net)
    assert summary.results[0].status == "failed"
    assert "differs from manifest" in summary.results[0].reason
    assert f.read_bytes() == b"tampered"


@respx.mock
def test_one_failure_does_not_stop_others(tmp_data, small_params, net, quarter_zip):
    _mock_site({"2019q2": quarter_zip()})
    respx.get(f"{OLD}/2019q1_form345.zip").mock(return_value=httpx.Response(503))
    summary = _fetch(tmp_data, small_params, net)
    assert [r.status for r in summary.results] == ["failed", "stored"]


@respx.mock
def test_403_aborts_the_run(tmp_data, small_params, net):
    respx.get(LANDING).mock(return_value=httpx.Response(403))
    with pytest.raises(SecForbidden):
        _fetch(tmp_data, small_params, net)


@respx.mock
def test_refetch_writes_a_dated_copy(tmp_data, small_params, net, quarter_zip):
    _mock_site({"2019q1": quarter_zip(), "2019q2": quarter_zip()})
    _fetch(tmp_data, small_params, net)
    original = (tmp_data.sec_insider / "2019q1_form345.zip").read_bytes()
    summary = _fetch(tmp_data, small_params, net, refetch="2019q1")
    assert [r.status for r in summary.results] == ["stored"]
    copies = list(tmp_data.sec_insider.glob("2019q1_form345__refetch_*Z.zip"))
    assert len(copies) == 1
    assert (tmp_data.sec_insider / "2019q1_form345.zip").read_bytes() == original
    roles = [(e.key, e.role) for e in read_all(tmp_data.manifest)]
    assert roles.count(("2019q1", "refetch")) == 1


def test_unknown_quarter_is_rejected(tmp_data, small_params, net):
    with pytest.raises(ValueError):
        _fetch(tmp_data, small_params, net, keys=["2030q1"])
