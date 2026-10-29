"""Polite HTTP: 1-2 s between requests per host, exponential backoff on 429/5xx, fixed User-Agent."""

from __future__ import annotations

import random
import threading
import time
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from regtrack.config import get_settings

_last: dict[str, float] = {}
_lock = threading.Lock()
MIN_GAP, MAX_GAP = 1.0, 2.0


class RetryableHTTP(Exception):
    pass


def _pace(url: str) -> None:
    host = urlparse(url).netloc
    with _lock:
        gap = random.uniform(MIN_GAP, MAX_GAP)
        wait = _last.get(host, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()


def client() -> httpx.Client:
    # Windows certificate store (truststore): fills in missing intermediate certificates the way browsers do
    # (egazette.gov.in serves an incomplete chain); verification stays on.
    import ssl

    import truststore

    return httpx.Client(
        headers={"User-Agent": get_settings().user_agent, "Accept": "application/json, */*"},
        timeout=httpx.Timeout(60.0, connect=20.0),
        follow_redirects=True,
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    )


def _retryable(e: BaseException) -> bool:
    return isinstance(e, (RetryableHTTP, httpx.TransportError))


@retry(
    retry=retry_if_exception(_retryable),
    wait=wait_exponential(multiplier=2, min=2, max=120),
    stop=stop_after_attempt(6),
    reraise=True,
)
def get(c: httpx.Client, url: str, **kw) -> httpx.Response:
    _pace(url)
    r = c.get(url, **kw)
    if r.status_code == 429 or r.status_code >= 500:
        raise RetryableHTTP(f"HTTP {r.status_code} for {url}")
    return r
