"""GET 抓取：直接请求 URL，返回响应正文，不做渲染。"""

import os

import httpx

from agents.resume.marker.tools.adapters.base import Hit
from agents.resume.marker.tools.fetch import register
from agents.resume.marker.tools.fetch.base import Fetcher, Page, site_of

_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "15"))
_MAX_BYTES = int(os.getenv("FETCH_MAX_BYTES", "3000000"))
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            trust_env=False,
            headers=_HEADERS,
        )
    return _client


class GetFetcher(Fetcher):
    id = "get"
    label = "GET 直取"
    aliases = ("http",)

    async def fetch(self, hit: Hit) -> Page:
        url = (hit.url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return Page(url=url, error="unsupported scheme")

        try:
            resp = await _get_client().get(url)
        except httpx.TimeoutException:
            return Page(url=url, error=f"timeout {_TIMEOUT:g}s")
        except httpx.HTTPError as exc:
            return Page(url=url, error=f"connect failed: {exc}"[:60])

        if resp.status_code >= 400:
            return Page(url=url, error=f"http {resp.status_code}")

        text = resp.text[:_MAX_BYTES]
        if not text.strip():
            return Page(url=url, error="empty text")

        return Page(
            url=str(resp.url),
            title=hit.title,
            text=text,
            site=site_of(str(resp.url)),
            published=hit.published,
        )

    async def aclose(self) -> None:
        global _client
        if _client is not None:
            await _client.aclose()
            _client = None


register(GetFetcher())
