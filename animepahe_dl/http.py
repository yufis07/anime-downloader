"""HTTP client with browser TLS impersonation, retries and Cloudflare detection.

``curl_cffi`` is used when available because it reproduces Chrome's TLS/HTTP2
fingerprint, which Cloudflare checks together with the ``cf_clearance`` cookie.
Plain ``requests`` is used as a fallback.
"""

from __future__ import annotations

import random
import string
import threading
import time
from typing import Any
from urllib.parse import urlsplit

try:  # pragma: no cover - import guard
    from curl_cffi import requests as _cffi_requests
except ImportError:  # pragma: no cover
    _cffi_requests = None

try:  # pragma: no cover - import guard
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

_CHALLENGE_MARKERS = (
    "just a moment...",
    "cf-browser-verification",
    "challenge-platform",
    "cf_chl_opt",
    "attention required! | cloudflare",
    "ddos-guard",
    "checking your browser",
)


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class CloudflareChallenge(HttpError):
    """The site answered with an anti-bot challenge; the user must verify in a browser."""


class Response:
    def __init__(self, status: int, content: bytes, headers: dict[str, str], url: str) -> None:
        self.status = status
        self.content = content
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.content)


def _random_token(length: int = 16) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def is_challenge(status: int, headers: dict[str, str], body: bytes) -> bool:
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if status in (403, 429, 503):
        sample = body[:20000].decode("utf-8", errors="ignore").lower()
        return any(marker in sample for marker in _CHALLENGE_MARKERS)
    return False


class HttpClient:
    """Thread-safe HTTP client (one underlying session per thread)."""

    def __init__(
        self,
        user_agent: str = "",
        cookies: dict[str, str] | None = None,
        cookie_host: str = "",
        timeout: float = 30.0,
        retries: int = 4,
        backend: str = "auto",
    ) -> None:
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.cookies: dict[str, str] = dict(cookies or {})
        self.cookie_host = cookie_host
        self.timeout = timeout
        self.retries = retries
        if backend == "auto":
            backend = "curl_cffi" if _cffi_requests is not None else "requests"
        if backend == "curl_cffi" and _cffi_requests is None:
            backend = "requests"
        if backend == "requests" and _requests is None:
            raise RuntimeError("Install 'curl_cffi' (recommended) or 'requests'.")
        self.backend = backend
        self._local = threading.local()
        self._lock = threading.Lock()
        # Legacy DDoS-Guard check accepts any random __ddg2_ cookie.
        self.cookies.setdefault("__ddg2_", _random_token())

    # ------------------------------------------------------------------ identity
    def set_identity(self, user_agent: str | None, cookies: dict[str, str] | None) -> None:
        with self._lock:
            if user_agent:
                self.user_agent = user_agent
            if cookies:
                self.cookies.update(cookies)
            self.cookies.setdefault("__ddg2_", _random_token())
        # Drop cached sessions so new identity is used everywhere.
        self._local = threading.local()

    def set_cookie_host(self, host: str) -> None:
        self.cookie_host = host

    def _session(self) -> Any:
        session = getattr(self._local, "session", None)
        if session is None:
            if self.backend == "curl_cffi":
                session = _cffi_requests.Session(impersonate="chrome")
            else:
                session = _requests.Session()
            self._local.session = session
        return session

    def _cookie_header(self, url: str) -> str | None:
        host = urlsplit(url).hostname or ""
        base = self.cookie_host.lower()
        if not base or not (host == base or host.endswith("." + base)):
            return None
        with self._lock:
            items = list(self.cookies.items())
        return "; ".join(f"{k}={v}" for k, v in items) or None

    # ------------------------------------------------------------------ requests
    def get(
        self,
        url: str,
        *,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        check_challenge: bool = True,
    ) -> Response:
        hdrs = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            hdrs["Referer"] = referer
        cookie = self._cookie_header(url)
        if cookie:
            hdrs["Cookie"] = cookie
        if headers:
            hdrs.update(headers)

        attempts = (self.retries if retries is None else retries) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                raw = self._session().get(
                    url, headers=hdrs, timeout=timeout or self.timeout, allow_redirects=True
                )
                resp = Response(raw.status_code, raw.content, dict(raw.headers), str(raw.url))
            except Exception as exc:  # network error: retry
                last_error = HttpError(f"Network error for {url}: {exc}")
                self._local = threading.local()
                self._backoff(attempt)
                continue

            if check_challenge and is_challenge(resp.status, resp.headers, resp.content):
                raise CloudflareChallenge(
                    "The site is asking for a Cloudflare/DDoS-Guard browser check. "
                    "Use 'Verify in browser' and try again.",
                    resp.status,
                )
            if resp.status == 429 or resp.status >= 500:
                last_error = HttpError(f"HTTP {resp.status} for {url}", resp.status)
                self._backoff(attempt, rate_limited=resp.status == 429)
                continue
            if resp.status >= 400:
                raise HttpError(f"HTTP {resp.status} for {url}", resp.status)
            return resp
        assert last_error is not None
        raise last_error

    @staticmethod
    def _backoff(attempt: int, rate_limited: bool = False) -> None:
        delay = (2.0 if rate_limited else 0.5) * (2**attempt)
        time.sleep(min(delay, 20.0) + random.random() * 0.3)

    def post_json(self, url: str, payload: Any, *, timeout: float | None = None, retries: int | None = None) -> Any:
        """POST ``payload`` as JSON and return the decoded JSON answer (retries 429/5xx and network errors)."""
        import json

        attempts = (self.retries if retries is None else retries) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                raw = self._session().post(
                    url, data=json.dumps(payload), timeout=timeout or self.timeout,
                    headers={"User-Agent": self.user_agent, "Content-Type": "application/json",
                             "Accept": "application/json"},
                )
                status, content = raw.status_code, raw.content
            except Exception as exc:  # network error: retry
                last_error = HttpError(f"Network error for {url}: {exc}")
                self._local = threading.local()
                self._backoff(attempt)
                continue
            if status == 429 or status >= 500:
                last_error = HttpError(f"HTTP {status} for {url}", status)
                self._backoff(attempt, rate_limited=status == 429)
                continue
            if status >= 400:
                raise HttpError(f"HTTP {status} for {url}", status)
            try:
                return json.loads(content.decode("utf-8", "replace"))
            except ValueError as exc:
                raise HttpError(f"Invalid JSON from {url}") from exc
        assert last_error is not None
        raise last_error

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.get(url, **kwargs).text

    def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = self.get(url, **kwargs)
        try:
            return resp.json()
        except ValueError as exc:
            if is_challenge(403, resp.headers, resp.content):
                raise CloudflareChallenge("Cloudflare challenge page returned instead of JSON.") from exc
            raise HttpError(f"Invalid JSON from {url}") from exc

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        return self.get(url, **kwargs).content
