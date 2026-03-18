

from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from agent_to_agent.services.skillsManager import SkillsManager
from agent_to_agent.skillsCenter.skill_center import SkillCenter



class RuntimeAgent:

    def __init__(
        self,
        agent_id: int,
        user_id: int,
        name: str,
        model: str,
        api_key: str,
        system_prompt: Optional[str] = None,
    ):
        """
        初始化 RuntimeAgent。

        Args:
            agent_id:      数据库 agents 表主键 ID。
            user_id:       所属用户 ID。
            name:          Agent 名称（对应注册时的 model_name）。
            model:         模型名称，传入 ChatOpenAI 使用。
            api_key:       模型 API Key，用于鉴权。
            system_prompt: 系统提示词，构建 agent 时注入。
        """
        self.agent_id = agent_id
        self.user_id = user_id
        self.name = name
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt

        # 当前挂载的 skill 列表，技能变动后需重建agent
        self._skills: list[BaseTool] = SkillsManager().init_base_skills()

        # 大模型实例，所有推理请求均通过此 LLM 发起
        self._llm = ChatOpenAI(model=self.model, temperature=0,api_key=self.api_key) # 如需要流式输出设为 True

        # 首次构建 agent（初始挂载 DownloadSkillTool，运行时按需追加）
        self._agent_entity = self._build_agent_entity()


    def _build_agent_entity(self):
        # 构建 Agent（使用当前 _skills 列表）
        return create_agent(self._llm, self._skills, system_prompt="你是一个有用的助手，可以使用提供的工具来帮助用户。")


    def list_skills(self) -> list[str]:
        """返回当前已挂载的 skill 名称列表。"""
        return [s.name for s in self._skills]

    # ------------------------------------------------------------------
    # 自动 Skill 加载（接入 SkillCenter）
    # ------------------------------------------------------------------

    def load_skills_and_rebuild_agent(self, task_description: str) -> int:
        """
        根据任务描述，通过 SkillCenter 加载所需 skill 并重建 agent。

        已挂载的 skill 不重复添加；有新 skill 时才触发重建。
        返回本次新增的 skill 数量。
        """
        tools = SkillCenter.load_for_task(
            self._agent_entity,
            task_description,
        )
        added = 0
        # 批量检查哪些 skill 尚未挂载，避免重复重建 agent
        new_tools = []
        for tool in tools:
            if not any(s.name == tool.name for s in self._skills):
                new_tools.append(tool)

        # 批量添加新 skill
        if new_tools:
            self._skills.extend(new_tools)
            added = len(new_tools)
            print(f"[Agent:{self.name}] 批量添加 {added} 个新 skill: {[t.name for t in new_tools]}")
            self._agent_entity = self._build_agent_entity()
            print(f"[Agent:{self.name}] agent已重建，当前 skill 总数：{len(self._skills)}")
        else:
            print(f"[Agent:{self.name}] 所有 skill 已存在，无需添加")

        return added



    # ------------------------------------------------------------------
    # 调用
    # ------------------------------------------------------------------

    def invoke(self, user_message: str) -> str:
        """先按任务加载所需 skill，再调用 agent 执行推理，返回文本结果。"""
        self.load_skills_and_rebuild_agent(
            user_message
        )

        state = self._agent_entity.invoke({"input": user_message})
        return state["output"]

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """
        序列化 Agent 基本信息为字典。

        注意：不含 api_key 等敏感字段，仅用于响应和日志。
        """
        return {
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "name": self.name,
            "model": self.model
        }
