from agent_to_agent.skillsCenter.baseskills.downloadSkillTool import DownloadSkillTool
from agent_to_agent.skillsCenter.baseskills.heartbeatTool import HeartbeatTool
from agent_to_agent.skillsCenter.baseskills.agentConnectionTool import (
    CheckAgentPermissionTool,
    ListConnectionRequestsTool,
    RequestConnectionTool,
    RespondConnectionRequestTool,
)
from langchain_core.tools import BaseTool
from typing import Callable
from sqlalchemy.orm import Session






class SkillsManager:

    def init_base_skills(self, agent_id: int, user_id: int, db_session_func: Callable[[], Session] ) -> list[BaseTool]:
        """初始化 RuntimeAgent 的基础工具集合。"""
        return [
            DownloadSkillTool(),
            HeartbeatTool(agent_id=agent_id, db_session_func=db_session_func),
            RequestConnectionTool(agent_id=agent_id, db_session_func=db_session_func),
            RespondConnectionRequestTool(agent_id=agent_id, db_session_func=db_session_func),
            ListConnectionRequestsTool(agent_id=agent_id, db_session_func=db_session_func),
            CheckAgentPermissionTool(agent_id=agent_id, db_session_func=db_session_func),
        ]
