from pydantic import BaseModel


class AgentConnectionRequest(BaseModel):
    source_agent_id: int
    target_agent_id: int
    message: str | None = None


class AgentConnectionResponseRequest(BaseModel):
    task_id: int
    responder_agent_id: int
    accepted: bool
    response_message: str | None = None
