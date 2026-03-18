from sqlalchemy import BigInteger, Column, Enum, String, TIMESTAMP
from sqlalchemy.sql import func
from agent_to_agent.models import Base


class AgentStateHistory(Base):
    __tablename__ = "agent_state_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(BigInteger, nullable=False)
    old_status = Column(
        Enum("new", "wake", "active", "sleep", "destroy"), nullable=True
    )
    new_status = Column(
        Enum("new", "wake", "active", "sleep", "destroy"), nullable=True
    )
    node = Column(String(255), nullable=True)
    reason = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
