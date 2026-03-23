from typing import Callable, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session


class _ConnectionTargetInput(BaseModel):
    target_agent_id: int | None = Field(default=None, description="目标 Agent 的 ID")
    target_agent_name: str | None = Field(default=None, description="目标 Agent 的名称，例如 B")

    @model_validator(mode="after")
    def validate_target(self):
        if self.target_agent_id is None and not self.target_agent_name:
            raise ValueError("target_agent_id 和 target_agent_name 至少要提供一个")
        return self


class _RequestConnectionInput(_ConnectionTargetInput):
    message: str | None = Field(default=None, description="附带给对方的连接申请说明")


class _RespondConnectionInput(BaseModel):
    task_id: int = Field(description="需要响应的连接申请任务 ID")
    accepted: bool = Field(description="是否同意这条连接申请")
    response_message: str | None = Field(default=None, description="给对方的响应说明")


class _ListConnectionRequestsInput(BaseModel):
    include_waiting_online: bool = Field(
        default=True,
        description="是否包含等待上线后才能看到的连接申请",
    )


class _CheckPermissionInput(_ConnectionTargetInput):
    action: str = Field(
        description="要检查的动作，例如 add_friend / send_message / assign_task / wake_and_deliver_task"
    )


class RequestConnectionTool(BaseTool):
    """让当前 RuntimeAgent 代表自己向目标 Agent 发起好友连接申请。"""

    name: str = "request_connection"
    description: str = (
        "当用户希望与另一个 Agent 建立好友关系时使用。"
        "可以按目标 Agent 名称或 ID 发起连接申请，系统会自动判断是直接建立、拒绝还是创建申请任务。"
    )
    args_schema: type[BaseModel] = _RequestConnectionInput

    agent_id: int = Field(exclude=True)
    db_session_func: Optional[Callable[[], Session]] = None

    def _run(
        self,
        target_agent_id: int | None = None,
        target_agent_name: str | None = None,
        message: str | None = None,
    ) -> str:
        """发起连接申请，并返回系统给当前 Agent 的结构化结果。"""
        from agent_to_agent.services.agentManager import AgentManager

        db = next(self.db_session_func())
        try:
            manager = AgentManager(db)
            resolved_target_id = manager.resolve_agent_id(
                target_agent_id=target_agent_id,
                target_agent_name=target_agent_name,
            )
            result = manager.request_connection(
                source_agent_id=self.agent_id,
                target_agent_id=resolved_target_id,
                message=message,
            )
            return str(result)
        finally:
            db.close()

    async def _arun(
        self,
        target_agent_id: int | None = None,
        target_agent_name: str | None = None,
        message: str | None = None,
    ) -> str:
        return self._run(
            target_agent_id=target_agent_id,
            target_agent_name=target_agent_name,
            message=message,
        )


class RespondConnectionRequestTool(BaseTool):
    """让当前 RuntimeAgent 处理一条收到的连接申请。"""

    name: str = "respond_connection_request"
    description: str = (
        "当用户希望同意或拒绝一条收到的好友连接申请时使用。"
        "需要提供连接申请任务 ID 和是否同意。"
    )
    args_schema: type[BaseModel] = _RespondConnectionInput

    agent_id: int = Field(exclude=True)
    db_session_func: Optional[Callable[[], Session]] = None

    def _run(self, task_id: int, accepted: bool, response_message: str | None = None) -> str:
        """响应一条连接申请任务。"""
        from agent_to_agent.services.agentManager import AgentManager

        db = next(self.db_session_func())
        try:
            manager = AgentManager(db)
            result = manager.respond_connection_request(
                task_id=task_id,
                responder_agent_id=self.agent_id,
                accepted=accepted,
                response_message=response_message,
            )
            return str(result)
        finally:
            db.close()

    async def _arun(self, task_id: int, accepted: bool, response_message: str | None = None) -> str:
        return self._run(task_id=task_id, accepted=accepted, response_message=response_message)


class ListConnectionRequestsTool(BaseTool):
    """让当前 RuntimeAgent 查看自己待处理的连接申请。"""

    name: str = "list_connection_requests"
    description: str = (
        "当用户想查看当前 Agent 收到的好友连接申请时使用。"
        "会返回待处理的连接申请任务列表。"
    )
    args_schema: type[BaseModel] = _ListConnectionRequestsInput

    agent_id: int = Field(exclude=True)
    db_session_func: Optional[Callable[[], Session]] = None

    def _run(self, include_waiting_online: bool = True) -> str:
        """列出当前 Agent 的待处理连接申请。"""
        from agent_to_agent.services.agentManager import AgentManager

        db = next(self.db_session_func())
        try:
            manager = AgentManager(db)
            result = manager.list_connection_requests_for_tool(
                target_agent_id=self.agent_id,
                include_waiting_online=include_waiting_online,
            )
            return str(result)
        finally:
            db.close()

    async def _arun(self, include_waiting_online: bool = True) -> str:
        return self._run(include_waiting_online=include_waiting_online)


class CheckAgentPermissionTool(BaseTool):
    """让当前 RuntimeAgent 在发起动作前主动检查目标 Agent 的权限结果。"""

    name: str = "check_agent_permission"
    description: str = (
        "当需要预先判断某个 Agent 动作是否允许时使用。"
        "支持检查 add_friend、send_message、assign_task、wake_and_deliver_task 等动作。"
    )
    args_schema: type[BaseModel] = _CheckPermissionInput

    agent_id: int = Field(exclude=True)
    db_session_func: Optional[Callable[[], Session]] = None

    def _run(
        self,
        action: str,
        target_agent_id: int | None = None,
        target_agent_name: str | None = None,
    ) -> str:
        """检查当前 Agent 对目标 Agent 的某个动作权限。"""
        from agent_to_agent.services.agentManager import AgentManager

        db = next(self.db_session_func())
        try:
            manager = AgentManager(db)
            resolved_target_id = manager.resolve_agent_id(
                target_agent_id=target_agent_id,
                target_agent_name=target_agent_name,
            )
            result = manager.check_permission(
                source_agent_id=self.agent_id,
                target_agent_id=resolved_target_id,
                action=action,
            )
            return str(result)
        finally:
            db.close()

    async def _arun(
        self,
        action: str,
        target_agent_id: int | None = None,
        target_agent_name: str | None = None,
    ) -> str:
        return self._run(
            action=action,
            target_agent_id=target_agent_id,
            target_agent_name=target_agent_name,
        )
