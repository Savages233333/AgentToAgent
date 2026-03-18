"""利用工厂模式创建并管理内存中的 RuntimeAgent，可通过 user_id 查询或移除。"""

import threading
from typing import Optional
from agent_to_agent.models.runtimeAgent import RuntimeAgent


class AgentFactory:
    """
    单例工厂，负责创建并管理内存中的 RuntimeAgent。
    容器以 user_id 为键，每个用户对应一个活跃 Agent。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._container: dict[int, RuntimeAgent] = {}
        return cls._instance

    def create(self, agent_id: int, user_id: int, name: str, model: str, api_key: str) -> RuntimeAgent:
        """创建 RuntimeAgent 并存入容器，若已存在则覆盖。"""
        agent = RuntimeAgent(
            agent_id=agent_id,
            user_id=user_id,
            name=name,
            model=model,
            api_key=api_key,
        )
        self._container[user_id] = agent
        return agent

    def get(self, user_id: int) -> Optional[RuntimeAgent]:
        """根据 user_id 获取容器中的 Agent。"""
        return self._container.get(user_id)

    def remove(self, user_id: int) -> None:
        """从容器中移除 Agent。"""
        self._container.pop(user_id, None)

    def exists(self, user_id: int) -> bool:
        return user_id in self._container
