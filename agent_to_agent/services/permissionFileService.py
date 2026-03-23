import json
from pathlib import Path


_PERMISSION_DIR = Path(__file__).resolve().parent.parent / "agentpermission"


class PermissionFileService:
    def create_permission_file(
        self,
        agent_id: int,
        user_id: int,
        role_type: str | None,
        level_rank: int | None,
        manager_agent_id: int | None,
    ) -> Path:
        """创建指定 Agent 的默认权限文件。"""
        _PERMISSION_DIR.mkdir(parents=True, exist_ok=True)
        file_path = self._file_path(agent_id)
        payload = {
            "version": 1,
            "agent_id": agent_id,
            "user_id": user_id,
            "default_relation_policy": "request",
            "friendship": {
                "allow_from": [],
                "deny_from": [],
                "require_request_from": ["*"],
            },
            "message": {
                "allow_direct_message_from_friends": True,
                "allow_direct_message_from_manager": True,
                "allow_direct_message_from_subordinates": True,
            },
            "task": {
                "allow_task_from_manager": True,
                "allow_task_from_subordinates": False,
                "allow_task_from_friends": False,
                "allow_auto_wake_for_task": False,
            },
            "organization": {
                "role_type": role_type or "staff",
                "level_rank": level_rank,
                "manager_agent_id": manager_agent_id,
            },
            "relations": {
                "friends": [],
                "blocked": [],
            },
        }
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return file_path

    def delete_permission_file(self, agent_id: int) -> None:
        """删除指定 Agent 的权限文件。"""
        file_path = self._file_path(agent_id)
        if file_path.exists():
            file_path.unlink()

    def permission_file_path(self, agent_id: int) -> Path:
        """返回指定 Agent 的权限文件路径。"""
        return self._file_path(agent_id)

    def load_permission_file(self, agent_id: int) -> dict:
        """读取并解析指定 Agent 的权限文件。"""
        file_path = self._file_path(agent_id)
        if not file_path.exists():
            raise FileNotFoundError(f"agent {agent_id} 的权限文件不存在：{file_path}")

        try:
            # 权限文件是权限引擎的静态策略源，运行时按需读取。
            return json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"agent {agent_id} 的权限文件不是合法 JSON") from exc

    @staticmethod
    def _file_path(agent_id: int) -> Path:
        return _PERMISSION_DIR / f"{agent_id}.permission.json"
