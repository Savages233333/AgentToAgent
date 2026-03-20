from pydantic import BaseModel

class AgentRequest(BaseModel):
    user_id: str
    api_key: str
    agent_id: int
    model_name: str
    messages: str