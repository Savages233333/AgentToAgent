from agent_to_agent.skillsCenter.baseskills.downloadSkillTool import DownloadSkillTool
from agent_to_agent.skillsCenter.baseskills.heartbeatTool import HeartbeatTool
from langchain_core.tools import BaseTool
from typing import Callable
from sqlalchemy.orm import Session






class SkillsManager:

    def init_base_skills(self, agent_id: int, user_id: int, db_session_func: Callable[[], Session] ) -> list[BaseTool]:

        return [DownloadSkillTool(),HeartbeatTool(agent_id=agent_id, db_session_func=db_session_func)]
