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
    callback_url: str | None = None
    callback_enabled: bool | None = None
    callback_secret: str | None = None
    callback_timeout_seconds: int | None = None
