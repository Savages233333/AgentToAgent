
from datetime import datetime,timezone


from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Callable, Optional
from sqlalchemy.orm import Session





class _HeartbeatInput(BaseModel):
    reason: str = Field(default="heartbeat", description="心跳上报的原因或当前活动描述")


class HeartbeatTool(BaseTool):
    """
    向系统上报心跳，保持 agent 活跃状态。

    当 agent 正在执行长时间任务时，应定期调用此工具防止被回收。
    自动更新数据库中的 last_active 时间戳。
    """

    name: str = "heartbeat"
    description: str = (
        "向系统上报心跳，保持 agent 活跃状态。"
        "当执行长时间任务（如批量处理、复杂计算、多轮对话）时，"
        "应每 5-10 分钟调用一次，防止被系统误判为闲置而回收。"
        "输入可以是当前活动描述或简单的 'working'。"
    )
    args_schema: type[BaseModel] = _HeartbeatInput

    # 注入必要依赖
    agent_id: int = Field(exclude=True)
    db_session_func: Optional[Callable[[], Session]] = None

    def _run(self, reason: str = "heartbeat") -> str:
        """上报心跳，更新 last_active 时间戳。"""
        from agent_to_agent.models.agentInfo import AgentInfo

        if not self.db_session_func:
            # 记录警告但不报错（允许 agent 在没有 db_session 时运行）
            print(
                f"[HeartbeatTool] 警告：db_session 未初始化，"
                f"无法更新 agent(id={self.agent_id}) 的心跳"
            )
            return "警告：心跳上报失败（数据库会话未初始化）"

        try:
            # 每次调用时获取新 session
            db = next(self.db_session_func())
            try:
                db.query(AgentInfo).filter(
                    AgentInfo.id == self.agent_id
                ).update({
                    "last_active": datetime.now(timezone.utc)
                })
                db.commit()
                return f"心跳已上报（reason: {reason}），agent 保持活跃状态"
            finally:
                db.close()  # ← 确保关闭
        except Exception as e:
            return f"心跳上报失败：{str(e)}"

    async def _arun(self, reason: str = "heartbeat") -> str:
        return self._run(reason)