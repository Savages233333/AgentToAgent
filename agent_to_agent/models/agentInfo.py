from sqlalchemy import BigInteger, Boolean, Column, Enum, JSON, String, TIMESTAMP
from sqlalchemy.sql import func
from agent_to_agent.models import Base


class AgentInfo(Base):
    __tablename__ = "agents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    name = Column(String(100), nullable=False)
    # Agent 在组织中的角色类型，例如 staff / manager / boss。
    role_type = Column(String(50), nullable=True)
    # Agent 在组织中的层级序号，数值越大表示层级越高。
    level_rank = Column(BigInteger, nullable=True)
    # Agent 的直属上级 agent_id，用于表达汇报关系。
    manager_agent_id = Column(BigInteger, nullable=True)
    # User 系统接收 Agent 主动回传结果的回调地址，未配置时为空。
    callback_url = Column(String(500), nullable=True)
    # 是否启用主动回调；为 False 时只保留任务和内部消息补偿。
    callback_enabled = Column(Boolean, nullable=True, default=False)
    # 回调签名密钥，用于给 User 系统验签。
    callback_secret = Column(String(255), nullable=True)
    # 回调超时时间（秒），避免远程调用长时间阻塞业务线程。
    callback_timeout_seconds = Column(BigInteger, nullable=True)
    model = Column(String(100), nullable=True)
    api_key = Column(String(255), nullable=True)
    status = Column(
        Enum("new", "wake", "active", "sleep", "destroy"),
        default="new",
        nullable=True,
    )
    current_node = Column(String(255), nullable=True)
    context = Column(JSON, nullable=True)
    last_active = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
