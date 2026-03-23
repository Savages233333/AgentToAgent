
from datetime import datetime,timezone
from typing import Callable, Optional
from sqlalchemy.orm import Session

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
        db_session_func: Optional[Callable[[], Session]] = None,  # ← 改为工厂函数
    ):
        """
        初始化 RuntimeAgent。

        Args:
            agent_id:      数据库 agents 表主键 ID。
            user_id:       所属用户 ID。
            name:          Agent 名称（对应注册时的 model_name）。
            model:         模型名称，传入 ChatOpenAI 使用。
            api_key:       模型 API Key，用于鉴权。
            db_session:    数据库会话，用于心跳更新 last_active。
            system_prompt: 系统提示词，构建 agent 时注入。
        """
        self.agent_id = agent_id
        self.user_id = user_id
        self.name = name
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.db_session_func = db_session_func
        # 系统内部事件收件箱，用于承载其他 Agent 回传给当前 Agent 的通知。
        self._system_messages: list[dict] = []

        # 当前挂载的 skill 列表，技能变动后需重建agent
        self._skills: list[BaseTool] = SkillsManager().init_base_skills(self.agent_id, self.user_id, db_session_func)

        # 大模型实例，所有推理请求均通过此 LLM 发起
        self._llm = ChatOpenAI(model=self.model, temperature=0,api_key=self.api_key) # 如需要流式输出设为 True

        # 首次构建 agent（初始挂载 DownloadSkillTool，运行时按需追加）
        self._agent_entity = self._build_agent_entity()

    def _update_last_active(self):
        """更新数据库中的 last_active 时间戳。"""
        if self.db_session_func:
            try:
                from agent_to_agent.models.agentInfo import AgentInfo
                from agent_to_agent.models import get_db
                # 获取新的 session
                db = next(self.db_session_func())
                try:
                    db.query(AgentInfo).filter(
                        AgentInfo.id == self.agent_id
                    ).update({
                        "last_active": datetime.now(timezone.utc)
                    })
                    db.commit()
                finally:
                    db.close()  # ← 确保关闭
            except Exception as e:
                print(f"[RuntimeAgent:{self.name}] 更新 last_active 失败：{e}")


    def _build_agent_entity(self):
        """基于当前工具集合构建 RuntimeAgent 的执行实体。"""
        # 基础系统提示会显式告知 Agent：
        # 连接申请、权限检查、任务查询等系统动作应优先通过工具完成，而不是凭空假设结果。
        return create_agent(
            self._llm,
            self._skills,
            system_prompt=(
                "你是一个有用的助手，可以使用提供的工具来帮助用户。"
                "当用户涉及 Agent 之间的好友连接、权限判断、查看连接申请或响应连接申请时，"
                "必须优先调用系统工具获取真实结果。"
                "如果你有 requires_user_action 的待处理任务，也应优先提醒用户处理。"
            ),
        )


    def list_skills(self) -> list[str]:
        """返回当前已挂载的 skill 名称列表。"""
        return [s.name for s in self._skills]

    def check_inbox(self) -> list[dict]:
        """读取当前 Agent 的任务收件箱，用于在上线后快速感知待处理事项。"""
        if not self.db_session_func:
            return []

        from agent_to_agent.services.agentManager import AgentManager

        db = next(self.db_session_func())
        try:
            manager = AgentManager(db)
            return manager.list_my_tasks(target_agent_id=self.agent_id, include_completed=False)
        finally:
            db.close()

    def receive_system_message(
        self,
        message_type: str,
        event_type: str,
        payload: dict,
        from_agent_id: int | None = None,
        from_agent_name: str | None = None,
    ) -> None:
        """接收一条由系统或其他 Agent 注入的内部消息。"""
        self._system_messages.append(
            {
                "message_type": message_type,
                "event_type": event_type,
                "payload": payload,
                "from_agent_id": from_agent_id,
                "from_agent_name": from_agent_name,
            }
        )

    def pending_system_message_count(self) -> int:
        """返回当前尚未被消费的内部系统消息数量。"""
        return len(self._system_messages)

    def _consume_system_message_context(self) -> str:
        """把暂存的系统消息转成当前轮次可消费的上下文，并在消费后清空。"""
        if not self._system_messages:
            return ""

        parts: list[str] = []
        for item in self._system_messages:
            source = item.get("from_agent_name") or item.get("from_agent_id") or "system"
            parts.append(
                f"系统事件: type={item['message_type']}, event={item['event_type']}, "
                f"from={source}, payload={item['payload']}"
            )

        self._system_messages.clear()
        return (
            "在回答当前用户之前，请先处理以下系统事件，并在合适时优先把结果反馈给用户：\n"
            + "\n".join(parts)
        )

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
        self._update_last_active()

        """先按任务加载所需 skill，再调用 agent 执行推理，返回文本结果。"""
        system_context = self._consume_system_message_context()
        effective_message = user_message
        if system_context:
            effective_message = f"{system_context}\n\n用户消息：{user_message}"

        self.load_skills_and_rebuild_agent(
            effective_message
        )

        state = self._agent_entity.invoke({"input": effective_message})
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
