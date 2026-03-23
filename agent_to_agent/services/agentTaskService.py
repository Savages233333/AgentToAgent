from datetime import datetime, timezone

from sqlalchemy.orm import Session

from agent_to_agent.models.agentTask import AgentTask
from agent_to_agent.models.agentTaskEvent import AgentTaskEvent


class AgentTaskService:
    def __init__(self, db: Session) -> None:
        """初始化 Agent 任务服务。"""
        self.db = db

    def create_task(
        self,
        task_type: str,
        source_agent_id: int,
        target_agent_id: int,
        payload: dict | None = None,
        requires_user_action: bool = False,
        priority: int = 0,
        status: str = "pending",
        expires_at: datetime | None = None,
    ) -> AgentTask:
        """创建一条任务，并自动记录 created 事件。"""
        task = AgentTask(
            task_type=task_type,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            status=status,
            payload=payload,
            requires_user_action=requires_user_action,
            priority=priority,
            expires_at=expires_at,
        )
        self.db.add(task)
        self.db.flush()
        self.add_task_event(
            task_id=task.id,
            event_type="created",
            event_payload={
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.db.flush()
        return task

    def add_task_event(
        self,
        task_id: int,
        event_type: str,
        event_payload: dict | None = None,
    ) -> AgentTaskEvent:
        """为指定任务追加一条事件记录。"""
        event = AgentTaskEvent(
            task_id=task_id,
            event_type=event_type,
            event_payload=event_payload,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def update_task_status(
        self,
        task_id: int,
        status: str,
        event_type: str = "status_changed",
        event_payload: dict | None = None,
    ) -> AgentTask:
        """更新任务状态，并同步记录一条状态变更事件。"""
        task = self.get_task(task_id)
        task.status = status
        self.db.add(task)
        payload = event_payload.copy() if event_payload else {}
        payload["status"] = status
        self.add_task_event(
            task_id=task_id,
            event_type=event_type,
            event_payload=payload,
        )
        self.db.flush()
        return task

    def get_task(self, task_id: int) -> AgentTask:
        """读取指定任务，不存在则抛错。"""
        task = self.db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if not task:
            raise ValueError(f"任务不存在：{task_id}")
        return task

    def list_pending_tasks_for_agent(self, target_agent_id: int) -> list[AgentTask]:
        """查询目标 Agent 当前待处理的任务。"""
        return (
            self.db.query(AgentTask)
            .filter(
                AgentTask.target_agent_id == target_agent_id,
                AgentTask.status.in_(["pending", "queued", "delivered", "waiting_user"]),
            )
            .order_by(AgentTask.priority.desc(), AgentTask.created_at.asc())
            .all()
        )

    def list_task_events(self, task_id: int) -> list[AgentTaskEvent]:
        """按时间顺序返回指定任务的所有事件。"""
        return (
            self.db.query(AgentTaskEvent)
            .filter(AgentTaskEvent.task_id == task_id)
            .order_by(AgentTaskEvent.created_at.asc())
            .all()
        )

    def list_tasks_for_agent(
        self,
        target_agent_id: int,
        statuses: list[str] | None = None,
    ) -> list[AgentTask]:
        """按状态查询目标 Agent 的任务列表。"""
        query = self.db.query(AgentTask).filter(AgentTask.target_agent_id == target_agent_id)
        if statuses:
            query = query.filter(AgentTask.status.in_(statuses))
        return query.order_by(AgentTask.priority.desc(), AgentTask.created_at.asc()).all()
