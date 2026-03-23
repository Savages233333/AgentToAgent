from sqlalchemy import BigInteger, Column, JSON, String, TIMESTAMP
from sqlalchemy.sql import func

from agent_to_agent.models import Base


class AgentTaskEvent(Base):
    __tablename__ = "agent_task_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # 事件所属的任务 ID。
    task_id = Column(BigInteger, nullable=False)
    # 事件类型，例如 created / queued / delivered / accepted / rejected。
    event_type = Column(String(100), nullable=False)
    # 事件详情，用于保存状态变化原因或附加上下文。
    event_payload = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
