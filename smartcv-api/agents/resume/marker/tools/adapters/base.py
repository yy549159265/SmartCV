"""来源适配器：输入一组检索词，输出 URL 列表。

每个来源一个文件，模块末尾 `register(...)` 注册；
新增来源只加文件，采集逻辑不用改。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agents.resume.marker.schemas.market import Brief


@dataclass(slots=True)
class Hit:
    """一条待抓取的链接；user_tag 只有用户补充的网址才有。"""

    url: str
    title: str = ""
    published: str = ""
    user_tag: dict | None = None


class Source(ABC):
    """来源适配器接口。

    label 是前端勾选时传进来的名字；dims 为空表示这个来源适用于所有维度。
    """

    id: str = ""
    label: str = ""
    aliases: tuple[str, ...] = ()
    dims: tuple[str, ...] = ()

    @abstractmethod
    async def urls(
        self,
        queries: list[str],
        *,
        limit: int,
        brief: Brief,
        settings: dict[str, str] | None = None,
    ) -> list[Hit]:
        """返回至多 limit 条链接；失败返回空列表，不要抛异常。

        brief 是本次调研归一化后的简报（岗位、城市、年限、时间窗口等），
        适配器可以据此拼平台检索条件；settings 是用户为该来源预先填写的
        动态参数，键和值统一用英文枚举（如腾讯的 recruitType:
        experienced / campus），未配置时为空字典。
        """


@dataclass(slots=True)
class SourceBinding:
    """一次检索用到的来源及其动态参数。"""

    source: Source
    settings: dict[str, str] = field(default_factory=dict)
