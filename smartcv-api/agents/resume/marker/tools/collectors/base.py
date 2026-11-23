"""采集适配器：输入一组检索词，输出带正文的页面列表。

与来源适配器（tools/adapters）的分工：

  来源适配器  只做「检索词 → URL」，不关心正文怎么拿；
  采集适配器  负责整条采集链路：有的接口先检索再逐页抓取（searxng），
              有的接口检索时直接返回正文（deepseek），不再受目标站点反爬影响。

子类只实现 collect()：整次调用失败就抛异常，由 collect.py 转成该维度的跳过原因；
单条结果失败返回 Page(error=...) 即可，失败页会和抓取失败一样上报给前端。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.fetch.base import Page


@dataclass(slots=True)
class CollectField:
    """采集方式需要用户填写的参数；secret 的字段前端按密码框渲染。"""

    key: str
    label: str
    placeholder: str = ""
    secret: bool = False


class Collector(ABC):
    """采集方式接口；id / label 与前端的「采集方式」选项一一对应。"""

    id: str = ""
    label: str = ""
    aliases: tuple[str, ...] = ()
    fields: tuple[CollectField, ...] = ()

    @abstractmethod
    async def collect(
        self,
        queries: list[str],
        *,
        limit: int,
        brief: Brief,
        settings: dict[str, str],
        fetch_mode: str = "get",
    ) -> list[Page]:
        """采集一个维度的页面。

        limit 是本维度最多要几页；fetch_mode 只给需要二次抓取正文的实现用，
        自带正文的接口（deepseek）忽略它。
        """
