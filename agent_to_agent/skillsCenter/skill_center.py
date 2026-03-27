import json
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from agent_to_agent.utils import ExecutableSkillTool, MarkdownSkillUtil




_AGENT_DIR = Path(__file__).parent.parent
_SKILLS_DIR = _AGENT_DIR / "skillsCenter" / "skills"
_LOCK_FILE = _SKILLS_DIR / ".skills_store_lock.json"
_ALL_SKILLS_FILE = _AGENT_DIR / "static" / "allskills.json"

_ANALYZE_PROMPT = """\
你是一个 skill 选择器。下面是 skillhub 上所有可用 skill 的列表（JSON 格式），以及用户的任务描述。

规则：
1. 如果任务是纯问答，不需要任何外部工具，直接返回空 JSON 数组 []
2. 否则，分析任务需要哪些能力类型，从列表中选出匹配的 skill
3. 同一类型能力有多个 skill 候选时，只选 downloads 最高的那一个
4. 只返回 JSON 数组，不要包含任何解释文字
5. 每项包含以下字段：id、name、slug、description、downloads

skill 列表：
{all_skills}

用户任务描述：
{task_description}
"""


class SkillCenter:

    @staticmethod
    def load_for_task(agent: Any, task_description: str) -> list[BaseTool]:
        """
        利用 agent 内置的 LLM 从 allskills.json 中为任务选出最合适的 skill，
        已安装的直接加载，未安装的触发 DownloadSkillTool 下载后再加载。

        Args:
            agent:            RuntimeAgent 内部的 AgentExecutor，持有 LLM 与 DownloadSkillTool。
            task_description: 用户任务描述，用于 LLM 分析选 skill。

        Returns:
            list[BaseTool]：可直接挂载到 agent 的工具列表；纯问答场景返回空列表。
        """
        # 第一阶段：LLM 分析，选出所需 skill
        selected = SkillCenter._analyze_skills(agent,task_description)
        if not selected:
            return []

        # 第二阶段：遍历，已安装直接加载，未安装触发 agent 下载后再加载
        lock = SkillCenter._read_lock()
        tools: list[BaseTool] = []

        for skill in selected:
            slug = skill.get("slug", "")
            if not slug:
                continue

            if slug not in lock.get("skills", {}):
                # 未安装：invoke agent 触发 DownloadSkillTool 完成下载及 lock 更新
                agent.invoke({"input": f"请下载安装 skill: {slug}"})

            tool = SkillCenter._load_local(slug)
            if tool is not None:
                tools.append(tool)

        return tools

    @staticmethod
    def _analyze_skills(agent: Any, task_description: str) -> list[dict]:
        """
        通过 agent.invoke 分析任务描述，从 allskills.json 中选出所需 skill。

        纯问答任务返回 []；同类型多个 skill 时只选 downloads 最高的一个。
        agent 持有 LLM，直接复用其推理能力，无需单独实例化模型。
        """
        if not _ALL_SKILLS_FILE.exists():
            return []

        all_skills = _ALL_SKILLS_FILE.read_text(encoding="utf-8")
        prompt = _ANALYZE_PROMPT.format(
            all_skills=all_skills,
            task_description=task_description,
        )


        response = agent.invoke({"input": prompt})

        # 解析 LLM 返回的 JSON，兼容 markdown 代码块包裹
        try:
            content = response["output"]
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            return []

    @staticmethod
    def _read_lock() -> dict:
        """读取 .skills_store_lock.json，文件缺失或损坏时返回空结构。"""
        if not _LOCK_FILE.exists():
            return {"version": 1, "skills": {}}
        try:
            return json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"version": 1, "skills": {}}

    @staticmethod
    def _load_local(slug: str) -> BaseTool | None:
        """
        从本地 skill 目录构建工具实例。

        Args:
            slug: skill 标识符，对应 skillsCenter/skills/<slug>/ 目录。

        Returns:
            BaseTool 实例；目录或 SKILL.md 不存在时返回 None。
        """
        skill_dir = _SKILLS_DIR / slug
        skill_md = skill_dir / "SKILL.md"
        meta_json = skill_dir / "_meta.json"
        if not skill_md.exists():
            return None

        content = skill_md.read_text(encoding="utf-8")
        name = description = ""

        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                for line in content[3:end].splitlines():
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()

        if not name or not description:
            return None

        meta = {}
        if meta_json.exists():
            try:
                meta = json.loads(meta_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}

        entrypoint = meta.get("entrypoint")
        if isinstance(entrypoint, dict):
            entry_type = entrypoint.get("type")
            script = entrypoint.get("script")
            if entry_type == "python" and isinstance(script, str) and script.strip():
                return ExecutableSkillTool(
                    name=name,
                    description=description,
                    skill_dir=str(skill_dir),
                    script_path=script,
                )

        return MarkdownSkillUtil(name=name, description=description, skill_content=content)
