"""Fetching a visitor's link safely (spec §5.3, §8: protection when accepting URLs).

Only http(s) on the standard ports; every hop of a redirect is checked; the host must resolve to public
addresses only (no localhost, private networks, link-local, cloud metadata); size and time are limited;
only HTML is read. Errors are split into temporary (retry later) and permanent (give up).
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
USER_AGENT = "EventCalendarBot/1.0 (+https://eventcalendar.com.ua)"
TEMPORARY_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}


class Blocked(ValueError):
    pass


@dataclass
class FetchResult:
    ok: bool
    url: str
    html: str = ""
    status: int = 0
    error: str = ""
    temporary: bool = False


def default_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)]


def check_url(url: str, resolver=default_resolver) -> None:
    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        raise Blocked("only http and https links")
    if p.port not in (None, 80, 443):
        raise Blocked("non-standard port")
    if p.username or p.password:
        raise Blocked("credentials in URL")
    host = (p.hostname or "").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise Blocked("local host name")
    try:
        addrs = [host] if _is_ip(host) else resolver(host)
    except socket.gaierror as e:
        raise Blocked(f"host does not resolve: {e}") from e
    if not addrs:
        raise Blocked("host does not resolve")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise Blocked(f"address {ip} is not public")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def safe_fetch(url: str, *, client: httpx.Client | None = None, resolver=default_resolver) -> FetchResult:
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False,
                                    headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                check_url(url, resolver)
            except Blocked as e:
                return FetchResult(False, url, error=f"blocked: {e}")
            try:
                with client.stream("GET", url) as r:
                    if r.is_redirect:
                        loc = r.headers.get("location")
                        if not loc:
                            return FetchResult(False, url, status=r.status_code, error="redirect without location")
                        url = urljoin(url, loc)
                        continue
                    if r.status_code >= 400:
                        return FetchResult(False, url, status=r.status_code, error=f"HTTP {r.status_code}",
                                           temporary=r.status_code in TEMPORARY_STATUS)
                    ctype = r.headers.get("content-type", "").lower()
                    if "html" not in ctype and "xml" not in ctype:
                        return FetchResult(False, url, status=r.status_code, error=f"not a web page ({ctype or '?'})")
                    body = b""
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break
                    enc = r.encoding or "utf-8"
                    return FetchResult(True, url, html=body[:MAX_BYTES].decode(enc, errors="replace"),
                                       status=r.status_code)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
                return FetchResult(False, url, error=f"{type(e).__name__}: {e}"[:300], temporary=True)
        return FetchResult(False, url, error="too many redirects")
    finally:
        if own:
            client.close()
