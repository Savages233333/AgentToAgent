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
    # 任务分组，用于区分审批、通知、连接关系、管理任务等视图。
    task_group = Column(String(100), nullable=True)
    # 是否需要目标用户显式处理该任务。
    requires_user_action = Column(Boolean, nullable=False, default=False)
    # 是否已经通知过目标用户。
    user_notified = Column(Boolean, nullable=False, default=False)
    # 任务优先级，数值越大优先级越高。
    priority = Column(BigInteger, nullable=False, default=0)
    # 当前任务已经重试的次数。
    retry_count = Column(BigInteger, nullable=False, default=0)
    # 当前任务允许的最大重试次数。
    max_retries = Column(BigInteger, nullable=False, default=3)
    # 最近一次处理失败原因。
    last_error = Column(String(1000), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    # 用户或 Agent 首次查看该任务的时间。
    read_at = Column(TIMESTAMP, nullable=True)
    # 最近一次成功送达/推送的时间。
    last_delivered_at = Column(TIMESTAMP, nullable=True)
    # 最近一次通知目标用户的时间。
    user_notified_at = Column(TIMESTAMP, nullable=True)
    # 任务完成时间。
    completed_at = Column(TIMESTAMP, nullable=True)
    # 任务取消时间。
    cancelled_at = Column(TIMESTAMP, nullable=True)
    expires_at = Column(TIMESTAMP, nullable=True)
