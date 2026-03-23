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
        task_group: str | None = None,
        requires_user_action: bool = False,
        user_notified: bool = False,
        priority: int = 0,
        max_retries: int = 3,
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
            task_group=task_group,
            requires_user_action=requires_user_action,
            user_notified=user_notified,
            priority=priority,
            max_retries=max_retries,
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

    def list_inbox_tasks(self, target_agent_id: int) -> list[AgentTask]:
        """返回当前 Agent 收件箱中的待处理任务。"""
        return self.list_tasks_for_agent(
            target_agent_id=target_agent_id,
            statuses=["pending", "queued", "delivered", "waiting_user", "waiting_target_online"],
        )

    def list_notification_tasks(self, target_agent_id: int) -> list[AgentTask]:
        """返回当前 Agent 的通知类任务。"""
        return (
            self.db.query(AgentTask)
            .filter(
                AgentTask.target_agent_id == target_agent_id,
                AgentTask.task_group == "notification",
            )
            .order_by(AgentTask.created_at.desc())
            .all()
        )

    def list_history_tasks(self, target_agent_id: int) -> list[AgentTask]:
        """返回当前 Agent 已完成、已拒绝或已取消的历史任务。"""
        return self.list_tasks_for_agent(
            target_agent_id=target_agent_id,
            statuses=["done", "accepted", "rejected", "cancelled", "expired"],
        )

    def list_failed_tasks(self, target_agent_id: int) -> list[AgentTask]:
        """返回当前 Agent 失败或进入死信的任务。"""
        return self.list_tasks_for_agent(
            target_agent_id=target_agent_id,
            statuses=["failed", "push_failed", "dead_letter"],
        )

    def mark_task_read(self, task_id: int) -> AgentTask:
        """标记任务已被用户或 Agent 查看。"""
        task = self.get_task(task_id)
        if task.read_at is None:
            task.read_at = datetime.now(timezone.utc)
            self.db.add(task)
            self.add_task_event(
                task_id=task_id,
                event_type="read",
                event_payload={"read_at": task.read_at.isoformat()},
            )
            self.db.flush()
        return task

    def mark_task_notified(self, task_id: int) -> AgentTask:
        """标记任务已成功通知过目标用户。"""
        task = self.get_task(task_id)
        task.user_notified = True
        task.user_notified_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.add_task_event(
            task_id=task_id,
            event_type="user_notified",
            event_payload={"user_notified_at": task.user_notified_at.isoformat()},
        )
        self.db.flush()
        return task

    def mark_task_delivered(self, task_id: int, reason: str | None = None) -> AgentTask:
        """标记任务已成功送达，并记录最近送达时间。"""
        task = self.update_task_status(
            task_id=task_id,
            status="delivered",
            event_type="delivered",
            event_payload={"reason": reason or "task delivered"},
        )
        task.last_delivered_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.flush()
        return task

    def increment_retry(self, task_id: int, error_message: str | None = None) -> AgentTask:
        """增加任务重试次数，并记录最近一次错误。"""
        task = self.get_task(task_id)
        task.retry_count = (task.retry_count or 0) + 1
        task.last_error = error_message
        self.db.add(task)
        self.add_task_event(
            task_id=task_id,
            event_type="retry_incremented",
            event_payload={
                "retry_count": task.retry_count,
                "last_error": error_message,
            },
        )
        self.db.flush()
        return task

    def mark_task_failed(self, task_id: int, error_message: str) -> AgentTask:
        """标记任务失败并记录失败原因。"""
        task = self.update_task_status(
            task_id=task_id,
            status="failed",
            event_type="failed",
            event_payload={"error": error_message},
        )
        task.last_error = error_message
        self.db.add(task)
        self.db.flush()
        return task

    def mark_task_completed(self, task_id: int, reason: str | None = None) -> AgentTask:
        """标记任务已完成。"""
        task = self.update_task_status(
            task_id=task_id,
            status="done",
            event_type="done",
            event_payload={"reason": reason or "task completed"},
        )
        task.completed_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.flush()
        return task

    def mark_task_cancelled(self, task_id: int, reason: str | None = None) -> AgentTask:
        """标记任务已取消。"""
        task = self.update_task_status(
            task_id=task_id,
            status="cancelled",
            event_type="cancelled",
            event_payload={"reason": reason or "task cancelled"},
        )
        task.cancelled_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.flush()
        return task

    def mark_task_expired(self, task_id: int, reason: str | None = None) -> AgentTask:
        """标记任务已过期。"""
        task = self.update_task_status(
            task_id=task_id,
            status="expired",
            event_type="expired",
            event_payload={"reason": reason or "task expired"},
        )
        self.db.add(task)
        self.db.flush()
        return task
