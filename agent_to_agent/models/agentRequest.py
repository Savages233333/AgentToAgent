from pydantic import BaseModel

class AgentRequest(BaseModel):
    user_id: int
    api_key: str
    agent_id: int | None = None
    model_name: str | None = None
    messages: str | None = None
    role_type: str | None = None
    level_rank: int | None = None
    manager_agent_id: int | None = None
