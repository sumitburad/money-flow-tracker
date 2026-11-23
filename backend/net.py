"""Dependable HTTP for public data sources.

What this module adds on top of plain ``requests``:

* **Retries** timeouts, dropped connections and temporary server errors
  (HTTP 429 and 5xx) with a growing pause between attempts.
* **Circuit breaker** per host: when one host has failed completely twice in
  the same run, later calls to that host fail at once instead of waiting
  again. The caller's fallback source then takes over quickly.
* **No secrets in text**: API keys and tokens are removed from error messages
  and from anything written to disk (see ``redact`` and ``scrub_secrets``).

``HTTP`` is a ready-made shared instance. The backend modules already accept an
injectable ``http=`` / ``session=`` argument, so tests can still pass a fake.
"""
from __future__ import annotations

import os
import random
import re
import time
from urllib.parse import urlparse

import requests

RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
RETRY_ERRORS = (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError)
# Environment variables that hold credentials. Values are never logged or saved.
SECRET_ENV_NAMES = ("FRED_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                    "UPSTOX_ANALYTICS_TOKEN")
_QUERY_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|key)=([^&\s'\"]+)")
# The look of a Google API key, as a second safety net next to the exact-value check above.
_GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_-]{30,}")


def _secret_values():
    found = []
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if len(value) >= 8:
            found.append(value)
    return found


def scrub_secrets(text):
    """Replace the exact value of any configured secret. Used on files we write."""
    out = str(text)
    for value in _secret_values():
        out = out.replace(value, "***")
    return _GOOGLE_KEY.sub("***", out)


def redact(text):
    """Make text safe to log: hide ``api_key=...`` style parameters and secret values."""
    out = _QUERY_SECRET.sub(lambda m: m.group(1) + "=***", str(text))
    return scrub_secrets(out)


class HostCircuitOpen(requests.ConnectionError):
    """Raised without any network call: this host already failed twice in this run."""


class RetryingHttp:
    """``get`` with retries, a per-host circuit breaker and secret-safe errors."""

    def __init__(self, attempts=3, backoff=1.5, max_delay=30.0, breaker_after=2,
                 sleep=time.sleep, fetcher=None, jitter=True):
        self.attempts = max(1, int(attempts))
        self.backoff = float(backoff)
        self.max_delay = float(max_delay)
        self.breaker_after = int(breaker_after)
        self._sleep = sleep
        self._fetch = fetcher or requests.get
        self._jitter = jitter
        self._failed_calls = {}

    def reset(self):
        """Forget past failures (tests, or a deliberate fresh start)."""
        self._failed_calls.clear()

    def _delay(self, attempt, response=None):
        delay = self.backoff * (2 ** (attempt - 1))
        headers = getattr(response, "headers", None) or {}
        try:
            delay = max(delay, float(headers.get("Retry-After")))
        except (TypeError, ValueError):
            pass
        if self._jitter:
            delay += random.uniform(0, 0.5)
        return min(delay, self.max_delay)

    @staticmethod
    def _clean(exc):
        """Strip secrets from an exception before it can be printed or stored."""
        try:
            exc.args = tuple(redact(arg) for arg in exc.args)
            if hasattr(exc, "request"):
                exc.request = None
            if hasattr(exc, "response"):
                exc.response = None
        except Exception:  # pragma: no cover - defensive only
            pass
        exc.__cause__ = None
        exc.__context__ = None
        exc.__suppress_context__ = True
        return exc

    def get(self, url, params=None, timeout=15, headers=None, **kwargs):
        host = urlparse(url).netloc.lower()
        if self._failed_calls.get(host, 0) >= self.breaker_after:
            raise HostCircuitOpen("skipping %s: it already failed %d times in this run"
                                  % (host, self._failed_calls[host]))
        last_error, last_response = None, None
        for attempt in range(1, self.attempts + 1):
            try:
                response = self._fetch(url, params=params, timeout=timeout,
                                       headers=headers, **kwargs)
            except RETRY_ERRORS as exc:
                last_error, last_response = exc, None
            else:
                if response.status_code not in RETRY_STATUS:
                    self._failed_calls[host] = 0
                    return response
                last_error, last_response = None, response
            if attempt < self.attempts:
                self._sleep(self._delay(attempt, last_response))
        self._failed_calls[host] = self._failed_calls.get(host, 0) + 1
        if last_response is not None:
            # Hand the final error response back; callers use raise_for_status().
            return last_response
        raise self._clean(last_error)


def retry_after_seconds(response, default=15.0, cap=30.0):
    """How long a busy server asked us to wait (HTTP Retry-After), kept between 1 s and ``cap``."""
    headers = getattr(response, "headers", None) or {}
    value = headers.get("Retry-After", headers.get("retry-after", default))
    try:
        wait = float(value)
    except (TypeError, ValueError):
        wait = float(default)
    return min(max(wait, 1.0), float(cap))


def post_with_one_429_retry(http, url, *, sleep=time.sleep, **kwargs):
    """POST once; if a free plan answers HTTP 429 (busy), wait as asked and try one more time.

    Returns the last response, so callers still use ``raise_for_status()``. At most two
    requests are ever made, which keeps a free daily request allowance safe.
    """
    response = http.post(url, **kwargs)
    if getattr(response, "status_code", None) == 429:
        sleep(retry_after_seconds(response))
        response = http.post(url, **kwargs)
    return response


HTTP = RetryingHttp()
