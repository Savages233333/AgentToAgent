from dataclasses import dataclass

from sqlalchemy.orm import Session

from agent_to_agent.models.agentInfo import AgentInfo
from agent_to_agent.services.agentTaskService import AgentTaskService
from agent_to_agent.services.permissionService import PermissionDecision, PermissionService


@dataclass(slots=True)
class TaskDispatchResult:
    task_id: int | None
    delivery_status: str
    target_status: str
    reason: str


class AgentTaskDispatchService:
    def __init__(
        self,
        db: Session,
        task_service: AgentTaskService | None = None,
        permission_service: PermissionService | None = None,
    ) -> None:
        """初始化任务投递策略服务。"""
        self.db = db
        self.task_service = task_service or AgentTaskService(db)
        self.permission_service = permission_service or PermissionService(db)

    def dispatch_task(
        self,
        task_type: str,
        source_agent_id: int,
        target_agent_id: int,
        payload: dict | None = None,
        requires_user_action: bool = False,
        priority: int = 0,
        permission_action: str = "assign_task",
    ) -> TaskDispatchResult:
        """根据目标 Agent 当前状态决定任务是立即送达、排队等待还是直接拒绝。"""
        decision = self.permission_service.check(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            action=permission_action,
        )
        target_agent = self._get_agent(target_agent_id)

        if decision.result == "deny":
            return TaskDispatchResult(
                task_id=None,
                delivery_status="rejected",
                target_status=target_agent.status,
                reason=decision.reason,
            )

        if target_agent.status == "destroy":
            return TaskDispatchResult(
                task_id=None,
                delivery_status="target_destroyed",
                target_status=target_agent.status,
                reason="目标 Agent 已销毁，无法接收任务",
            )

        initial_status, delivery_status, reason = self._resolve_delivery_plan(
            target_status=target_agent.status,
            permission_decision=decision,
        )
        task = self.task_service.create_task(
            task_type=task_type,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            payload=payload,
            requires_user_action=requires_user_action,
            priority=priority,
            status=initial_status,
        )

        self.task_service.add_task_event(
            task_id=task.id,
            event_type=delivery_status,
            event_payload={
                "reason": reason,
                "target_status": target_agent.status,
                "permission_result": decision.result,
                "permission_action": permission_action,
            },
        )
        return TaskDispatchResult(
            task_id=task.id,
            delivery_status=delivery_status,
            target_status=target_agent.status,
            reason=reason,
        )

    def deliver_pending_tasks_on_connect(self, target_agent_id: int) -> list[dict]:
        """在目标 Agent 上线后，把待处理任务批量推进到可处理状态。"""
        tasks = self.task_service.list_pending_tasks_for_agent(target_agent_id)
        delivered: list[dict] = []
        for task in tasks:
            if task.status in {"pending", "queued", "waiting_target_online"}:
                updated = self.task_service.update_task_status(
                    task_id=task.id,
                    status="delivered",
                    event_type="delivered",
                    event_payload={"reason": "target agent connected"},
                )
                delivered.append(
                    {
                        "task_id": updated.id,
                        "task_type": updated.task_type,
                        "status": updated.status,
                    }
                )
        return delivered

    def dispatch_system_task(
        self,
        task_type: str,
        source_agent_id: int,
        target_agent_id: int,
        payload: dict | None = None,
        requires_user_action: bool = False,
        priority: int = 0,
    ) -> TaskDispatchResult:
        """投递系统生成的通知类任务，跳过权限判定，只按目标状态决定送达策略。"""
        target_agent = self._get_agent(target_agent_id)
        if target_agent.status == "destroy":
            return TaskDispatchResult(
                task_id=None,
                delivery_status="target_destroyed",
                target_status=target_agent.status,
                reason="目标 Agent 已销毁，无法接收系统通知",
            )

        initial_status, delivery_status, reason = self._resolve_system_delivery_plan(
            target_status=target_agent.status,
        )
        task = self.task_service.create_task(
            task_type=task_type,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            payload=payload,
            requires_user_action=requires_user_action,
            priority=priority,
            status=initial_status,
        )
        self.task_service.add_task_event(
            task_id=task.id,
            event_type=delivery_status,
            event_payload={
                "reason": reason,
                "target_status": target_agent.status,
                "system_task": True,
            },
        )
        return TaskDispatchResult(
            task_id=task.id,
            delivery_status=delivery_status,
            target_status=target_agent.status,
            reason=reason,
        )

    def _get_agent(self, agent_id: int) -> AgentInfo:
        """读取指定 Agent 的当前生命周期状态。"""
        agent = self.db.query(AgentInfo).filter(AgentInfo.id == agent_id).first()
        if not agent:
            raise ValueError(f"agent 不存在：{agent_id}")
        return agent

    @staticmethod
    def _resolve_delivery_plan(
        target_status: str,
        permission_decision: PermissionDecision,
    ) -> tuple[str, str, str]:
        """根据目标状态和权限结果，确定任务入库状态与投递结果。"""
        if target_status in {"wake", "active"}:
            if permission_decision.result == "request":
                return "waiting_user", "delivered", "目标 Agent 在线，已收到申请类任务"
            return "delivered", "delivered", "目标 Agent 在线，任务已立即送达"

        if target_status == "sleep":
            if permission_decision.result == "request":
                return "waiting_target_online", "waiting_target_online", "目标 Agent 未在线，待其上线后处理申请"
            return "queued", "queued", "目标 Agent 休眠中，任务已入队等待上线"

        if target_status == "new":
            return "waiting_target_online", "waiting_target_online", "目标 Agent 尚未激活，任务已记录等待上线"

        return "queued", "queued", "任务已入队等待后续处理"

    @staticmethod
    def _resolve_system_delivery_plan(target_status: str) -> tuple[str, str, str]:
        """根据目标状态决定系统通知任务的送达策略。"""
        if target_status in {"wake", "active"}:
            return "delivered", "delivered", "目标 Agent 在线，系统通知已送达"
        if target_status in {"sleep", "new"}:
            return "waiting_target_online", "waiting_target_online", "目标 Agent 未在线，系统通知等待其上线"
        return "queued", "queued", "系统通知已入队等待后续处理"
