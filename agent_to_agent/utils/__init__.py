from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class _SkillQuery(BaseModel):
    query: str = Field(description="针对该技能的具体问题或操作描述")


class MarkdownSkillUtil(BaseTool):
    """
    基于 SKILL.md 的知识型工具。

    LLM 通过 description 判断何时调用本工具；
    调用时将完整 SKILL.md 内容作为上下文返回，
    使 LLM 能够依据文档内容完成对应领域的推理与操作。
    """

    name: str
    description: str
    skill_content: str
    args_schema: type[BaseModel] = _SkillQuery

    def _run(self, query: str) -> str:
        """返回该 skill 的完整参考文档，供 LLM 在推理时使用。"""
        return self.skill_content

    async def _arun(self, query: str) -> str:
        return self.skill_content
