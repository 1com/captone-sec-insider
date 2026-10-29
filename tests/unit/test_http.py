import hashlib

import httpx
import pytest
import respx

from sentinel.raw.http import (
    RateLimiter,
    RetryExhausted,
    RetryPolicy,
    SecForbidden,
    make_client,
    request_with_retry,
    stream_to_file,
)

URL = "https://www.sec.gov/files/x.zip"
UA = "Test User test@example.com"


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def clock(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


@pytest.fixture
def fc():
    return FakeClock()


@pytest.fixture
def limiter(fc):
    return RateLimiter(5, 10, clock=fc.clock, sleep=fc.sleep)


@pytest.fixture
def policy(fc):
    return RetryPolicy(max_attempts=5, backoff_base=0.01, backoff_max=0.02, sleep=fc.sleep)


def test_rate_limiter_never_exceeds_ceiling_and_averages_target(fc, limiter):
    times = []
    for _ in range(60):
        limiter.wait()
        times.append(fc.t)
    for i, t in enumerate(times):
        assert sum(1 for u in times[i:] if u < t + 1.0) <= 10
    assert (len(times) - 1) / (times[-1] - times[0]) == pytest.approx(5, rel=0.01)


def test_rate_limiter_rejects_ceiling_above_sec_limit():
    with pytest.raises(ValueError):
        RateLimiter(5, 11)


@respx.mock
def test_429_with_retry_after_then_200(fc, limiter, policy):
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200)]
    )
    resp = request_with_retry(make_client(UA, 5), "GET", URL, limiter, policy)
    assert resp.status_code == 200
    assert route.call_count == 2
    assert max(fc.slept) >= 1


@respx.mock
def test_five_503s_exhaust_retries(limiter, policy):
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(RetryExhausted):
        request_with_retry(make_client(UA, 5), "GET", URL, limiter, policy)
    assert route.call_count == 5


@respx.mock
def test_timeout_then_200(limiter, policy):
    respx.get(URL).mock(side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200)])
    assert request_with_retry(make_client(UA, 5), "GET", URL, limiter, policy).status_code == 200


@respx.mock
def test_403_is_never_retried(limiter, policy):
    route = respx.get(URL).mock(return_value=httpx.Response(403))
    with pytest.raises(SecForbidden):
        request_with_retry(make_client(UA, 5), "GET", URL, limiter, policy)
    assert route.call_count == 1


@respx.mock
def test_every_request_carries_the_contact(limiter, policy):
    route = respx.get(URL).mock(side_effect=[httpx.Response(500), httpx.Response(200)])
    request_with_retry(make_client(UA, 5), "GET", URL, limiter, policy)
    assert [c.request.headers["User-Agent"] for c in route.calls] == [UA, UA]


@respx.mock
def test_stream_to_file_hashes_and_counts(tmp_path, limiter, policy):
    body = b"x" * 3_000_000
    respx.get(URL).mock(return_value=httpx.Response(200, content=body, headers={"ETag": "abc"}))
    part = tmp_path / "f.zip.part"
    result = stream_to_file(make_client(UA, 5), URL, part, limiter, policy)
    assert part.read_bytes() == body
    assert result.bytes == len(body)
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.etag == "abc"


class _BrokenStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b"partial"
        raise httpx.ReadError("connection reset")


@respx.mock
def test_stream_failure_leaves_no_part_file(tmp_path, limiter, fc):
    respx.get(URL).mock(return_value=httpx.Response(200, stream=_BrokenStream()))
    part = tmp_path / "f.zip.part"
    with pytest.raises(RetryExhausted):
        stream_to_file(
            make_client(UA, 5), URL, part, limiter, RetryPolicy(2, 0.01, 0.02, sleep=fc.sleep)
        )
    assert not part.exists()
