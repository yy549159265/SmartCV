import re
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import yaml
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.prebuilt import ToolRuntime
from langgraph.runtime import Runtime

# 技能根目录：相对本文件推导（agents/middleware/skillmiddleware.py → ../skill）。
# 不依赖进程启动时的 CWD，Windows / Linux 下路径都成立。
SKILL_ROOT = Path(__file__).resolve().parent.parent / "skill"


def _make_load_skill_tool(allowed_names: Sequence[str]) -> BaseTool:
    """创建「按需加载技能内容」的工具，白名单通过闭包绑定在实例上。"""

    @tool
    def load_skill_through_path(
        skill_name: str,
        runtime: ToolRuntime,
        file_path: Optional[str] = None,
    ) -> str:
        """
        按需加载技能内容或其资源文件。类似 cat 命令。

        Args:
            skill_name: 要加载的技能名称
            file_path: 可选，技能内文件的相对路径。
                       如果为 None，返回 SKILL.md 全文。
                       如果指定路径，返回该路径文件内容。
        """
        try:
            if skill_name not in allowed_names:
                raise ToolException(f"技能 '{skill_name}' 不在当前 Agent 的白名单中")

            skill_dir = SKILL_ROOT / skill_name

            # 不传 file_path → 加载 SKILL.md
            if file_path is None:
                skill_file = skill_dir / "SKILL.md"
                if not skill_file.exists():
                    raise ToolException(f"技能 '{skill_name}' 的 SKILL.md 缺失")
                return skill_file.read_text(encoding="utf-8")

            # 传了 file_path → 加载指定文件（类似 cat）
            target_file = skill_dir / file_path

            # 路径安全验证，防止 ../../../etc/passwd
            if not str(target_file.resolve()).startswith(str(skill_dir.resolve())):
                raise ToolException("非法的文件路径访问")

            if not target_file.exists():
                raise ToolException(f"文件 '{file_path}' 在技能 '{skill_name}' 中不存在")

            return target_file.read_text(encoding="utf-8")

        except ToolException:
            raise
        except Exception as e:
            raise ToolException(str(e))

    return load_skill_through_path


class SkillMiddleware(AgentMiddleware):
    """按名字白名单加载技能的中间件。

    用法：SkillMiddleware(["md2json", "resume"])
    只从 agents/skill/ 目录下找与名单同名的技能目录并加载。
    """

    def __init__(self, skill_names: Optional[Sequence[str]] = None):
        super().__init__()
        self._skill_names = list(skill_names or [])
        self.tools = [_make_load_skill_tool(self._skill_names)]

    def _parse_frontmatter(self, text: str) -> dict:
        """解析 YAML frontmatter"""
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if match:
            return yaml.safe_load(match.group(1)) or {}
        return {}

    def _load_skill_meta(self) -> list[dict]:
        """只加载白名单里指定的技能元数据（agents/skill/<name>/SKILL.md）"""
        skills_meta: dict[str, dict] = {}
        for name in self._skill_names:
            skill_file = SKILL_ROOT / name / "SKILL.md"
            if not skill_file.exists():
                continue
            meta = self._parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            meta.setdefault("name", name)
            meta["_path"] = str(skill_file.parent)
            skills_meta[meta["name"]] = meta
        return list(skills_meta.values())

    def _skills_addendum(self) -> str:
        """构建技能提示文本。无技能时返回空串。"""
        user_skills = self._load_skill_meta()
        if not user_skills:
            return ""
        lines = [f"- **{s['name']}**: {s.get('description', '')}" for s in user_skills]
        skills_prompt = "\n".join(lines)
        return (
            f"\n\n## 你可用的专属技能\n\n{skills_prompt}\n\n"
            "如需使用某个技能的详细指令，请调用 `load_skill_through_path(skill_name)` 加载完整说明。\n"
            "如需查看技能内的参考文档，请调用 `load_skill_through_path(skill_name, 'xxx')`。\n"
        )

    def before_agent(
        self,
        state: Dict[str, Any],
        runtime: Runtime,
        config: RunnableConfig,
    ) -> dict:
        """把技能说明拼到第一条系统消息上。

        前提：主提示词要作为第一条 SystemMessage 放进 state["messages"]（即调用
        create_agent 时不传 system_prompt 参数，而是在 invoke 的输入消息里放一条
        SystemMessage）。这样 before_agent 就能直接往 messages[0] 追加，最终只有
        一条 SystemMessage。如果 messages[0] 不是系统消息，才退化成新插一条。
        """
        addendum = self._skills_addendum()
        if not addendum:
            return {}
        messages = state.get("messages", [])
        if messages and isinstance(messages[0], SystemMessage):
            messages[0].content += addendum
        else:
            messages.insert(0, SystemMessage(content=addendum.strip()))
        return {"messages": messages}
