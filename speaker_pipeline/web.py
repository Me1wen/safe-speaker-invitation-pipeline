"""Allowlisted, rate-limited HTTP access with conservative robots handling."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .common import host_allowed

USER_AGENT = "SafeSpeakerPipeline/1.0 (official public pages; human-reviewed workflow)"


class FetchError(RuntimeError):
    """A page was blocked, unavailable, non-HTML, or outside the allowlist."""


@dataclass
class Page:
    url: str
    html: str


class OfficialWebClient:
    def __init__(
        self,
        *,
        allow_live_fetch: bool = False,
        delay_seconds: float = 1.5,
        timeout_seconds: float = 20.0,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.allow_live_fetch = allow_live_fetch
        self.delay_seconds = max(0.0, delay_seconds)
        self.timeout_seconds = max(1.0, timeout_seconds)
        self.fetcher = fetcher
        self._last_request_at = 0.0
        self._robots: dict[str, RobotFileParser | bool] = {}
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)

    def _get(self, url: str) -> requests.Response:
        self._wait()
        try:
            response = self.session.get(url, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise FetchError(f"Request failed for {url}: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()
        return response

    def _robots_rule(self, url: str) -> RobotFileParser | bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        robots_url = urljoin(origin, "/robots.txt")
        response = self._get(robots_url)
        if response.status_code == 404:
            rule: RobotFileParser | bool = True
        elif response.status_code in {401, 403}:
            rule = False
        elif response.ok:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            rule = parser
        else:
            rule = False
        self._robots[origin] = rule
        return rule

    def fetch(self, url: str, allowed_domains: tuple[str, ...]) -> str:
        if not host_allowed(url, allowed_domains):
            raise FetchError(f"URL is outside Allowed Domains: {url}")
        if self.fetcher is not None:
            try:
                return self.fetcher(url)
            except Exception as exc:
                raise FetchError(f"Fixture/custom fetch failed for {url}: {exc}") from exc
        if not self.allow_live_fetch:
            raise FetchError(
                "Live fetch is disabled. Re-run with --allow-live-fetch after approval."
            )
        rule = self._robots_rule(url)
        if (
            rule is False
            or isinstance(rule, RobotFileParser)
            and not rule.can_fetch(USER_AGENT, url)
        ):
            raise FetchError(f"robots/access policy disallows: {url}")
        response = self._get(url)
        if response.status_code in {401, 403}:
            raise FetchError(f"Website blocked access ({response.status_code}): {url}")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FetchError(f"Could not fetch {url}: {exc}") from exc
        content_type = response.headers.get("Content-Type", "")
        if content_type and "html" not in content_type.casefold():
            raise FetchError(f"Expected HTML, received {content_type}: {url}")
        return response.text
