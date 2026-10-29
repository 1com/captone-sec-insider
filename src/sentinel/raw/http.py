"""Rate-limited HTTP with retries, shared by every fetcher.

SEC fair access: at most 10 requests per second across the process, a contact User-Agent on every
request, and no retry after a 403 (retrying a rejected client is what gets it blocked).
"""

import hashlib
import logging
import os
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

SEC_RPS_CEILING = 10
CHUNK = 1 << 20


class SecForbidden(Exception):
    """The server rejected the client (HTTP 403). The whole run stops."""


class RetryExhausted(Exception):
    """A request kept failing with a transient error."""


class _Transient(Exception):
    def __init__(self, reason: str, retry_after: float | None = None):
        super().__init__(reason)
        self.retry_after = retry_after


class RateLimiter:
    """Spaces requests 1/target_rps apart, so no one-second window exceeds the ceiling."""

    def __init__(
        self,
        target_rps: float,
        max_rps: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if max_rps > SEC_RPS_CEILING:
            raise ValueError(f"max_rps must be <= {SEC_RPS_CEILING} (SEC fair-access policy)")
        if not 0 < target_rps <= max_rps:
            raise ValueError("target_rps must be positive and <= max_rps")
        self._interval = 1.0 / target_rps
        self._clock = clock
        self._sleep = sleep
        self._next: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._next is not None and now < self._next:
                self._sleep(self._next - now)
                now = self._next
            self._next = now + self._interval


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    backoff_base: float
    backoff_max: float
    sleep: Callable[[float], None] = field(default=time.sleep, compare=False)

    @classmethod
    def from_settings(cls, http: dict) -> RetryPolicy:
        """From the `http` section of config/sources.yaml."""
        return cls(http["max_attempts"], http["backoff_base_seconds"], http["backoff_max_seconds"])

    def delay(self, attempt: int, retry_after: float | None) -> float:
        jittered = random.uniform(0, min(self.backoff_max, self.backoff_base * 2 ** (attempt - 1)))
        return max(jittered, retry_after or 0.0)


def make_client(user_agent: str, timeout: float) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After", "")
    return float(value) if value.isdigit() else None


def _check_status(resp: httpx.Response, url: str) -> None:
    if resp.status_code == 403:
        raise SecForbidden(f"HTTP 403 for {url}")
    if resp.status_code == 429 or resp.status_code >= 500:
        raise _Transient(f"HTTP {resp.status_code}", _retry_after(resp))


def _with_retry(attempt_fn, url: str, limiter: RateLimiter, policy: RetryPolicy):
    for attempt in range(1, policy.max_attempts + 1):
        limiter.wait()
        log.debug("request t=%.3f %s (attempt %d)", time.monotonic(), url, attempt)
        try:
            return attempt_fn()
        except httpx.TransportError as e:
            reason, retry_after = f"{type(e).__name__}: {e}", None
        except _Transient as e:
            reason, retry_after = str(e), e.retry_after
        if attempt == policy.max_attempts:
            raise RetryExhausted(f"{url}: {reason} after {attempt} attempts")
        delay = policy.delay(attempt, retry_after)
        log.info("retrying %s in %.1fs (%s)", url, delay, reason)
        policy.sleep(delay)
    raise AssertionError("unreachable")


def request_with_retry(
    client: httpx.Client, method: str, url: str, limiter: RateLimiter, policy: RetryPolicy
) -> httpx.Response:
    """One request with retries on 429, 5xx and transport errors. Other statuses are returned."""

    def attempt():
        resp = client.request(method, url)
        _check_status(resp, url)
        return resp

    return _with_retry(attempt, url, limiter, policy)


@dataclass(frozen=True)
class StreamResult:
    bytes: int
    sha256: str
    url: str
    last_modified: str | None
    etag: str | None


def stream_to_file(
    client: httpx.Client, url: str, part_path: Path, limiter: RateLimiter, policy: RetryPolicy
) -> StreamResult:
    """Stream `url` into `part_path`, hashing on the fly; the part file is removed on failure."""

    def attempt():
        try:
            with client.stream("GET", url) as resp:
                _check_status(resp, url)
                resp.raise_for_status()
                digest, size = hashlib.sha256(), 0
                with open(part_path, "wb") as f:
                    for chunk in resp.iter_bytes(CHUNK):
                        f.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                return StreamResult(
                    bytes=size,
                    sha256=digest.hexdigest(),
                    url=str(resp.url),
                    last_modified=resp.headers.get("Last-Modified"),
                    etag=resp.headers.get("ETag"),
                )
        except BaseException:
            part_path.unlink(missing_ok=True)
            raise

    return _with_retry(attempt, url, limiter, policy)
