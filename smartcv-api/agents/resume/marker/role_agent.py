"""简历反推：读一份简历，给出 4 个可投递岗位和求职城市 / 年限。

配置区的轻量能力：一次结构化调用即可，不需要 agent / 工具 / checkpointer，
也不参与调研流水线，前端点「AI 反推」时单独调用。
city / experience 直接作为 MarketRequest 的输入，不写回简历。
"""

from datetime import date
from pathlib import Path

from langchain_openai import ChatOpenAI

from agents.resume.marker.schemas import RoleInference
from agents.resume.marker.utils.runner import run_structured
from agents.resume.marker.utils.stage_log import stage_info, stage_warning
from agents.utils.resume import resume_to_marked_text

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "plan" / "roles.md").read_text(encoding="utf-8")


def _empty() -> dict:
    return {"roles": [], "city": "", "experience": ""}


async def run(llm:ChatOpenAI, resume: list[dict]) -> dict:
    """返回 {roles, city, experience}；失败时 roles 为空由路由层报错。"""
    if not resume:
        stage_info("roles", "跳过", reason="无简历")
        return _empty()
    stage_info("roles", "开始", sections=len(resume))
    structured = await run_structured(
        llm.with_structured_output(RoleInference, method="json_mode"),
        _SYSTEM_PROMPT,
        f"<today>{date.today().isoformat()}</today>\n<resume>\n{resume_to_marked_text(resume)}\n</resume>",
        stage="roles",
    )
    if structured is None:
        stage_warning("roles", "未返回结构化结果")
        return _empty()

    result = RoleInference.model_validate(structured)
    roles: list[dict] = []
    seen: set[str] = set()
    for option in result.roles:
        title = option.title.strip()
        if not title or title in seen:
            continue
        seen.add(title)
        roles.append({"title": title, "reason": option.reason.strip()})

    stage_info("roles", "完成", count=len(roles), city=result.city.strip() or "-")
    return {
        "roles": roles,
        "city": result.city.strip()[:40],
        "experience": result.experience.strip()[:40],
    }
