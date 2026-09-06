"""
Web search module for DeepanCode.
Uses SearXNG public instances for reliable, API-free search.
Falls back to DuckDuckGo if SearXNG is unavailable.
Includes response caching and improved HTML parsing.
"""

import httpx
import ipaddress
import logging
import re
import json
import hashlib
import socket
import time
from typing import List, Dict, Optional
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("deepans_code.web_search")

ALLOWED_FETCH_PORTS = {80, 443}
MAX_FETCH_BYTES = 1_000_000  # 1MB cap before parsing
MAX_REDIRECTS = 3


def _is_ip_blocked(ip_str: str) -> bool:
    """True if IP is private/loopback/link-local/multicast/reserved/unspecified."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return True  # unparseable -> block


def is_safe_fetch_url(url: str) -> tuple:
    """Validate a fetch URL against SSRF. Returns (ok, reason)."""
    if not url or len(url) > 2048:
        return False, "URL empty or too long"
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Unparseable URL"
    if parsed.scheme not in ("http", "https"):
        return False, "Only http/https allowed"
    if not parsed.hostname:
        return False, "Missing hostname"
    # Block credentials in URL (user:pass@host exfiltration / confused deputy)
    if parsed.username or parsed.password:
        return False, "Credentials in URL not allowed"
    port = parsed.port
    if port is not None and port not in ALLOWED_FETCH_PORTS:
        return False, f"Port {port} blocked (80/443 only)"
    # Resolve hostname and check every A/AAAA record
    try:
        infos = socket.getaddrinfo(parsed.hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "DNS resolution failed"
    if not infos:
        return False, "DNS resolution failed"
    for _fam, _typ, _proto, _canon, sockaddr in infos:
        if _is_ip_blocked(sockaddr[0]):
            return False, f"Blocked IP {sockaddr[0]}"
    return True, "OK"

SEARXNG_INSTANCES = [
    "https://search.sapti.me",
    "https://searx.tiekoetter.com",
    "https://searx.be",
    "https://search.ononoki.org",
    "https://searxng.ch",
    "https://searx.work",
]

_search_cache: Dict[str, tuple] = {}
CACHE_TTL = 300  # 5 minutes


def _cache_key(query: str, max_results: int) -> str:
    return hashlib.sha256(f"{query}:{max_results}".encode()).hexdigest()


def search_web(query: str, max_results: int = 5, use_cache: bool = True) -> List[Dict]:
    if not (query or "").strip():
        return []
    max_results = max(1, min(int(max_results or 5), 20))
    if use_cache:
        key = _cache_key(query, max_results)
        if key in _search_cache:
            cached_time, cached_results = _search_cache[key]
            if time.time() - cached_time < CACHE_TTL:
                return cached_results

    # Primary: duckduckgo-search library (most reliable)
    results = _search_ddgs_lib(query, max_results)
    if results:
        if use_cache:
            _search_cache[_cache_key(query, max_results)] = (time.time(), results)
        return results

    # Fallback: SearXNG public instances
    results = _search_searxng(query, max_results)
    if results:
        if use_cache:
            _search_cache[_cache_key(query, max_results)] = (time.time(), results)
        return results

    # Fallback: DuckDuckGo HTML scraping
    results = _search_duckduckgo(query, max_results)
    if use_cache and results:
        _search_cache[_cache_key(query, max_results)] = (time.time(), results)
    return results


def _search_searxng(query: str, max_results: int) -> List[Dict]:
    for instance in SEARXNG_INSTANCES:
        try:
            with httpx.Client(timeout=8, follow_redirects=True) as client:
                response = client.get(
                    f"{instance}/search",
                    params={"q": query, "format": "json", "categories": "general"},
                    headers={"User-Agent": "DeepanCode/3.0"}
                )
                if response.status_code == 200:
                    data = response.json()
                    results = []
                    for item in data.get("results", [])[:max_results]:
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "snippet": item.get("content", "")[:200],
                            "engine": item.get("engine", "searxng"),
                            "score": item.get("score", 0)
                        })
                    if results:
                        return results
        except Exception as e:
            logger.debug(f"SearXNG {instance} failed: {e}")
            continue
    return []


def _search_ddgs_lib(query: str, max_results: int) -> List[Dict]:
    """Search using the ddgs Python library (most reliable)."""
    try:
        from ddgs import DDGS
        results = []
        with DDGS(timeout=10) as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")[:200],
                    "engine": "duckduckgo",
                    "score": max_results - len(results),
                })
        return results
    except Exception as e:
        logger.debug(f"ddgs library failed: {e}")
        return []


def _search_duckduckgo(query: str, max_results: int) -> List[Dict]:
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            response = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            response.raise_for_status()
            html = response.text
            result_pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
            snippet_pattern = r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>'
            urls = re.findall(result_pattern, html, re.DOTALL)
            snippets = re.findall(snippet_pattern, html, re.DOTALL)
            results = []
            for i in range(min(len(urls), max_results)):
                url = urls[i][0] if isinstance(urls[i], tuple) else urls[i]
                title = urls[i][1] if isinstance(urls[i], tuple) else ""
                title = re.sub(r'<[^>]+>', '', title).strip()
                snippet = re.sub(r'<[^>]+>', '', snippets[i] if i < len(snippets) else "").strip()
                if "uddg=" in url:
                    url = url.split("uddg=")[1].split("&")[0]
                    import urllib.parse
                    url = urllib.parse.unquote(url)
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "engine": "duckduckgo",
                    "score": max_results - i
                })
            return results
    except Exception as e:
        logger.error(f"DuckDuckGo search error: {e}")
        return []


def fetch_url_content(url: str, max_length: int = 8000) -> str:
    """Fetch and extract clean text from a URL with SSRF protection."""
    ok, reason = is_safe_fetch_url(url)
    if not ok:
        logger.warning(f"SSRF block: {url[:120]} — {reason}")
        return f"Error: Blocked URL ({reason})"
    try:
        # Manual redirect chain so every hop is re-validated for SSRF.
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            ok, reason = is_safe_fetch_url(current)
            if not ok:
                return f"Error: Blocked redirect ({reason})"
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                response = client.get(current, headers={
                    "User-Agent": "DeepanCode/3.0",
                    "Accept": "text/html,application/xhtml+xml"
                })
                if response.status_code in (301, 302, 303, 307, 308):
                    loc = response.headers.get("location", "")
                    if not loc:
                        return "Error: Empty redirect"
                    # Resolve relative redirects safely
                    from urllib.parse import urljoin
                    current = urljoin(current, loc)
                    continue
                response.raise_for_status()
                raw = response.content[:MAX_FETCH_BYTES]
                content = raw.decode(response.encoding or "utf-8", errors="replace")
                break
        else:
            return "Error: Too many redirects"

        # Post-fetch DNS recheck (rebinding mitigation): if the hostname now
        # resolves to a blocked IP, discard the body instead of serving it.
        # NOTE: this narrows but cannot fully close the check→fetch race;
        # see module docstring. Treat fetched content as untrusted regardless.
        ok, reason = is_safe_fetch_url(current)
        if not ok:
            logger.warning(f"SSRF post-fetch block: {current[:120]} — {reason}")
            return f"Error: Blocked URL ({reason})"

        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
        content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        content = re.sub(r'<nav[^>]*>.*?</nav>', '', content, flags=re.DOTALL)
        content = re.sub(r'<footer[^>]*>.*?</footer>', '', content, flags=re.DOTALL)
        content = re.sub(r'<header[^>]*>.*?</header>', '', content, flags=re.DOTALL)

        content = re.sub(r'<(h[1-6])[^>]*>(.*?)</\1>', r'\n## \2\n', content, flags=re.DOTALL)
        content = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', content, flags=re.DOTALL)
        content = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', content, flags=re.DOTALL)
        content = re.sub(r'<pre[^>]*>(.*?)</pre>', r'\n```\n\1\n```\n', content, flags=re.DOTALL)
        content = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', content, flags=re.DOTALL)

        content = re.sub(r'<[^>]+>', ' ', content)
        content = re.sub(r'\s+', ' ', content).strip()
        content = re.sub(r'\n{3,}', '\n\n', content)

        if len(content) > max_length:
            content = content[:max_length] + "\n\n... (truncated)"
        return content
    except httpx.TimeoutException:
        return f"Error: Timeout fetching {url}"
    except httpx.HTTPStatusError as e:
        return f"Error: HTTP {e.response.status_code} fetching {url}"
    except Exception as e:
        logger.error(f"Web fetch error: {e}")
        return f"Error fetching URL: {str(e)}"
