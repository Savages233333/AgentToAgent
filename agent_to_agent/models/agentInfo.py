from sqlalchemy import BigInteger, Column, Enum, JSON, String, TIMESTAMP
from sqlalchemy.sql import func
from agent_to_agent.models import Base


class AgentInfo(Base):
    __tablename__ = "agents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    name = Column(String(100), nullable=False)
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
