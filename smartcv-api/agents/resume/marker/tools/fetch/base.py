"""抓取适配器：输入 URL 列表，输出等长、同序的页面列表。

子类只实现 fetch(hit)；并发、保序、异常转 error 都在 fetch_list 里做。
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlsplit

from agents.resume.marker.tools.adapters.base import Hit


@dataclass(slots=True)
class Page:
    """一个 URL 的抓取结果；error 为空表示成功。"""

    url: str
    title: str = ""
    text: str = ""
    site: str = ""
    published: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def site_of(url: str) -> str:
    """取域名用于来源分组；取不到时返回空串。"""
    try:
        return (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return ""


class Fetcher(ABC):
    """抓取适配器接口；id / label 与前端 fetchMode 的取值一一对应。"""

    id: str = ""
    label: str = ""
    aliases: tuple[str, ...] = ()
    concurrency: int = 6

    @abstractmethod
    async def fetch(self, hit: Hit) -> Page:
        """抓一条；失败返回 Page(error="具体原因")，不要抛异常。"""

    async def fetch_list(self, hits: list[Hit]) -> list[Page]:
        """列表进、列表出：并发抓取，结果与入参等长同序。"""
        semaphore = asyncio.Semaphore(max(1, self.concurrency))
        pages: list[Page] = [Page(url=hit.url) for hit in hits]

        async def run(index: int, hit: Hit) -> None:
            async with semaphore:
                try:
                    page = await self.fetch(hit)
                except Exception as exc:
                    page = Page(url=hit.url, error=str(exc)[:60] or "fetch failed")
            pages[index] = page

        await asyncio.gather(*(run(index, hit) for index, hit in enumerate(hits)))
        return pages
