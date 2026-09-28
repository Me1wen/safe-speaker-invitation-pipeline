"""Allowlisted, rate-limited HTTP access with conservative robots handling."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .common import host_allowed

USER_AGENT = "SafeSpeakerPipeline/1.1 (official public pages; human-reviewed workflow)"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class FetchError(RuntimeError):
    """A page was blocked, unavailable, non-HTML, or outside the allowlist."""


@dataclass(frozen=True)
class Page:
    """Fetched HTML plus the provenance needed for later evidence capture."""

    url: str
    html: str
    final_url: str = ""
    status_code: int = 200
    content_type: str = ""
    retrieved_at: str = ""
    content_sha256: str = ""

    @property
    def requested_url(self) -> str:
        return self.url


REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5


class OfficialWebClient:
    def __init__(
        self,
        *,
        allow_live_fetch: bool = False,
        delay_seconds: float = 1.5,
        timeout_seconds: float = 20.0,
        fetcher: Callable[[str], str | Page] | None = None,
        resolver: Callable[[str, int], Iterable[str]] | None = None,
    ) -> None:
        self.allow_live_fetch = allow_live_fetch
        self.delay_seconds = max(0.0, delay_seconds)
        self.timeout_seconds = max(1.0, timeout_seconds)
        self.fetcher = fetcher
        self.resolver = resolver or self._resolve_addresses
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

    @staticmethod
    def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
        try:
            records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise FetchError(f"Could not resolve host {host}: {exc}") from exc
        return tuple(sorted({str(record[4][0]).split("%", 1)[0] for record in records}))

    @staticmethod
    def _public_address(address: str) -> bool:
        try:
            return ipaddress.ip_address(address.split("%", 1)[0]).is_global
        except ValueError:
            return False

    def _validate_public_url(self, url: str, allowed_domains: tuple[str, ...]) -> None:
        if not host_allowed(url, allowed_domains):
            raise FetchError(f"URL is outside Allowed Domains: {url}")
        parsed = urlparse(url)
        if parsed.username is not None or parsed.password is not None:
            raise FetchError(f"URL credentials are not allowed: {url}")
        host = parsed.hostname or ""
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise FetchError(f"URL has an invalid port: {url}") from exc
        if port not in {80, 443}:
            raise FetchError(f"URL uses a disallowed port ({port}): {url}")
        try:
            literal = ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            try:
                addresses = tuple(str(address) for address in self.resolver(host, port))
            except FetchError:
                raise
            except (OSError, TypeError, ValueError) as exc:
                raise FetchError(f"Could not resolve host {host}: {exc}") from exc
        else:
            addresses = (str(literal),)
        if not addresses:
            raise FetchError(f"Host resolved to no addresses: {host}")
        blocked = sorted(address for address in addresses if not self._public_address(address))
        if blocked:
            raise FetchError(f"URL resolves to a non-public address: {host} ({', '.join(blocked)})")

    def _get_once(self, url: str) -> requests.Response:
        self._wait()
        try:
            response = self.session.get(
                url,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise FetchError(f"Request failed for {url}: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()
        self._validate_response_size(response, url)
        return response

    @staticmethod
    def _validate_response_size(response: requests.Response, url: str) -> None:
        declared = str(response.headers.get("Content-Length", "")).strip()
        if declared:
            try:
                declared_size = int(declared)
            except ValueError as exc:
                raise FetchError(f"Invalid Content-Length while fetching {url}") from exc
            if declared_size < 0 or declared_size > MAX_RESPONSE_BYTES:
                raise FetchError(f"Response exceeds the 5 MiB limit: {url}")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise FetchError(f"Response exceeds the 5 MiB limit: {url}")

    def _robots_rule(self, url: str, allowed_domains: tuple[str, ...]) -> RobotFileParser | bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        robots_url = urljoin(origin, "/robots.txt")
        response, final_url = self._request_with_redirects(
            robots_url,
            allowed_domains,
            check_robots=False,
        )
        if response.status_code == 404:
            rule: RobotFileParser | bool = True
        elif response.status_code in {401, 403}:
            rule = False
        elif response.ok:
            parser = RobotFileParser()
            parser.set_url(final_url)
            parser.parse(response.text.splitlines())
            rule = parser
        else:
            rule = False
        self._robots[origin] = rule
        return rule

    def _robots_allows(self, url: str, allowed_domains: tuple[str, ...]) -> bool:
        rule = self._robots_rule(url, allowed_domains)
        return rule is True or isinstance(rule, RobotFileParser) and rule.can_fetch(USER_AGENT, url)

    def _request_with_redirects(
        self,
        url: str,
        allowed_domains: tuple[str, ...],
        *,
        check_robots: bool,
    ) -> tuple[requests.Response, str]:
        current = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            self._validate_public_url(current, allowed_domains)
            if check_robots and not self._robots_allows(current, allowed_domains):
                raise FetchError(f"robots/access policy disallows: {current}")
            response = self._get_once(current)
            response_url = str(getattr(response, "url", "") or current)
            self._validate_public_url(response_url, allowed_domains)
            if response.status_code not in REDIRECT_STATUSES:
                return response, response_url
            if redirect_count >= MAX_REDIRECTS:
                raise FetchError(f"Too many redirects while fetching: {url}")
            location = response.headers.get("Location", "").strip()
            if not location:
                raise FetchError(f"Redirect response has no Location header: {current}")
            next_url = urljoin(response_url, location)
            # Validate before the next request so an unsafe Location is never contacted.
            self._validate_public_url(next_url, allowed_domains)
            current = next_url
        raise FetchError(f"Too many redirects while fetching: {url}")

    @staticmethod
    def _fixture_page(url: str, result: str | Page) -> Page:
        if isinstance(result, Page):
            final_url = result.final_url or result.url or url
            return Page(
                url=url,
                html=result.html,
                final_url=final_url,
                status_code=result.status_code,
                content_type=result.content_type,
                retrieved_at=result.retrieved_at
                or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                content_sha256=result.content_sha256
                or hashlib.sha256(result.html.encode("utf-8")).hexdigest(),
            )
        return Page(
            url=url,
            html=result,
            final_url=url,
            retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            content_sha256=hashlib.sha256(result.encode("utf-8")).hexdigest(),
        )

    def fetch_page(self, url: str, allowed_domains: tuple[str, ...]) -> Page:
        if not host_allowed(url, allowed_domains):
            raise FetchError(f"URL is outside Allowed Domains: {url}")
        if self.fetcher is not None:
            try:
                page = self._fixture_page(url, self.fetcher(url))
            except Exception as exc:
                raise FetchError(f"Fixture/custom fetch failed for {url}: {exc}") from exc
            if not host_allowed(page.final_url, allowed_domains):
                raise FetchError(f"Fixture final URL is outside Allowed Domains: {page.final_url}")
            return page
        if not self.allow_live_fetch:
            raise FetchError(
                "Live fetch is disabled. Re-run with --allow-live-fetch after approval."
            )
        response, final_url = self._request_with_redirects(
            url,
            allowed_domains,
            check_robots=True,
        )
        if response.status_code in {401, 403}:
            raise FetchError(f"Website blocked access ({response.status_code}): {final_url}")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FetchError(f"Could not fetch {final_url}: {exc}") from exc
        content_type = response.headers.get("Content-Type", "")
        if content_type and "html" not in content_type.casefold():
            raise FetchError(f"Expected HTML, received {content_type}: {final_url}")
        html = response.text
        content = getattr(response, "content", None) or html.encode("utf-8")
        return Page(
            url=url,
            html=html,
            final_url=final_url,
            status_code=response.status_code,
            content_type=content_type,
            retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )

    def fetch(self, url: str, allowed_domains: tuple[str, ...]) -> str:
        """Compatibility wrapper returning HTML while fetch_page exposes provenance."""

        return self.fetch_page(url, allowed_domains).html
