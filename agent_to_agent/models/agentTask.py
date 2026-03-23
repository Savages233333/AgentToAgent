from sqlalchemy import BigInteger, Boolean, Column, JSON, String, TIMESTAMP
from sqlalchemy.sql import func

from agent_to_agent.models import Base


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # 任务类型，例如 friend_request / direct_message / manager_assignment。
    task_type = Column(String(100), nullable=False)
    # 发起任务的来源 Agent。
    source_agent_id = Column(BigInteger, nullable=False)
    # 接收任务的目标 Agent。
    target_agent_id = Column(BigInteger, nullable=False)
    # 任务当前状态，例如 pending / queued / delivered / waiting_user / done。
    status = Column(String(50), nullable=False, default="pending")
    # 任务负载，保存具体业务参数。
    payload = Column(JSON, nullable=True)
    # 是否需要目标用户显式处理该任务。
    requires_user_action = Column(Boolean, nullable=False, default=False)
    # 任务优先级，数值越大优先级越高。
    priority = Column(BigInteger, nullable=False, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    expires_at = Column(TIMESTAMP, nullable=True)
