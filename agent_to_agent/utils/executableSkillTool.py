from pathlib import Path
import subprocess

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class _ExecutableSkillQuery(BaseModel):
    query: str = Field(description="传递给该 skill 的任务描述或输入内容")


class ExecutableSkillTool(BaseTool):
    """
    可执行型 skill 工具。

    当前最小版只支持 Python 脚本入口，并通过 stdin 传递 query。
    """

    name: str
    description: str
    skill_dir: str
    script_path: str
    args_schema: type[BaseModel] = _ExecutableSkillQuery

    def _run(self, query: str) -> str:
        skill_root = Path(self.skill_dir).resolve()
        target_script = (skill_root / self.script_path).resolve()

        if skill_root not in target_script.parents:
            return "skill 执行失败：脚本路径非法，超出 skill 目录范围"

        if not target_script.exists():
            return f"skill 执行失败：脚本不存在 -> {self.script_path}"

        if not target_script.is_file():
            return f"skill 执行失败：目标不是文件 -> {self.script_path}"

        try:
            result = subprocess.run(
                ["python", str(target_script)],
                input=query,
                text=True,
                capture_output=True,
                timeout=30,
                cwd=str(skill_root),
            )
        except subprocess.TimeoutExpired:
            return "skill 执行失败：脚本执行超时"
        except Exception as exc:
            return f"skill 执行失败：{exc}"

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            return (
                f"skill 执行失败：exit_code={result.returncode}, stderr={stderr}"
            )

        stdout = (result.stdout or "").strip()
        if not stdout:
            return "skill 执行完成，但没有输出结果"

        return stdout

    async def _arun(self, query: str) -> str:
        return self._run(query)
