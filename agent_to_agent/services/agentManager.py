from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy.orm import Session
from agent_to_agent.models.agentInfo import AgentInfo
from agent_to_agent.models.agentTask import AgentTask
from agent_to_agent.models.agentStateHistory import AgentStateHistory
from agent_to_agent.factory.agentFactory import AgentFactory
from agent_to_agent.models.agentRequest import AgentRequest
from agent_to_agent.services.graphAgentService import GraphAgentNode, GraphAgentService
from agent_to_agent.services.permissionFileService import PermissionFileService
from agent_to_agent.services.permissionService import PermissionService
from agent_to_agent.services.agentTaskService import AgentTaskService
from agent_to_agent.services.agentTaskDispatchService import AgentTaskDispatchService
from agent_to_agent.services.agentCallbackService import AgentCallbackService

class AgentManager:
    def __init__(self, db: Session):
        """初始化 Agent 业务管理器及其依赖服务。"""
        self.db = db
        self.agent_factory = AgentFactory()
        from agent_to_agent.models import get_db
        self.db_session_func = get_db
        self.graph_service = GraphAgentService()
        self.permission_file_service = PermissionFileService()
        self.permission_service = PermissionService(
            db=self.db,
            permission_file_service=self.permission_file_service,
            graph_service=self.graph_service,
        )
        self.task_service = AgentTaskService(db=self.db)
        self.task_dispatch_service = AgentTaskDispatchService(
            db=self.db,
            task_service=self.task_service,
            permission_service=self.permission_service,
        )
        self.callback_service = AgentCallbackService()

    def agentRegister(self, req: AgentRequest):
        """
        注册新 agent。

        向 agents 表写入记录后，同时创建图数据库节点和权限文件。
        """
        agent = None
        graph_created = False
        permission_created = False

        try:
            agent = AgentInfo(
                user_id=req.user_id,
                name=req.model_name or "unnamed-agent",
                role_type=req.role_type,
                level_rank=req.level_rank,
                manager_agent_id=req.manager_agent_id,
                callback_url=req.callback_url,
                callback_enabled=req.callback_enabled if req.callback_enabled is not None else False,
                callback_secret=req.callback_secret,
                callback_timeout_seconds=req.callback_timeout_seconds or 5,
                model="qwen3-max",
                api_key=req.api_key,
                status="new",
            )
            self.db.add(agent)
            self.db.flush()

            self.graph_service.create_agent_node(
                GraphAgentNode(
                    agent_id=agent.id,
                    user_id=agent.user_id,
                    name=agent.name,
                    status=agent.status,
                    role_type=agent.role_type,
                    level_rank=agent.level_rank,
                    manager_agent_id=agent.manager_agent_id,
                )
            )
            graph_created = True

            permission_path = self.permission_file_service.create_permission_file(
                agent_id=agent.id,
                user_id=agent.user_id,
                role_type=agent.role_type,
                level_rank=agent.level_rank,
                manager_agent_id=agent.manager_agent_id,
            )
            permission_created = True

            history = AgentStateHistory(
                agent_id=agent.id,
                old_status=None,
                new_status="new",
                reason="agent registered",
            )
            self.db.add(history)
            self.db.commit()
            self.db.refresh(agent)
            return {
                "id": agent.id,
                "status": agent.status,
                "role_type": agent.role_type,
                "level_rank": agent.level_rank,
                "manager_agent_id": agent.manager_agent_id,
                "callback_url": agent.callback_url,
                "callback_enabled": agent.callback_enabled,
                "permission_file": str(permission_path),
            }
        except Exception as e:
            self.db.rollback()
            if permission_created and agent is not None:
                self.permission_file_service.delete_permission_file(agent.id)
            if graph_created and agent is not None:
                try:
                    self.graph_service.delete_agent_node(agent.id)
                except Exception:
                    pass
            raise HTTPException(status_code=500, detail=str(e))

    def connect(self, req: AgentRequest):
        """
        唤醒 agent，建立运行时连接。

        原子操作（异常自动回滚）：
        1. 查询 agents 表，校验 agent_id 与 api_key 匹配且状态为 new 或 sleep
        2. 调用 AgentFactory.create() 在内存容器中实例化 RuntimeAgent
        3. 将数据库状态更新为 wake，写入 AgentStateHistory 记录
        """
        try:
            agent = (
                self.db.query(AgentInfo)
                .filter(
                    AgentInfo.id == req.agent_id,
                    AgentInfo.api_key == req.api_key,
                    AgentInfo.status.in_(["new", "sleep"]),
                )
                .first()
            )
            if not agent:
                raise HTTPException(status_code=404, detail="agent 没有被注册喔")

            old_status = agent.status

            # 工厂创建运行时 Agent 存入内存容器
            self.agent_factory.create(
                agent_id=agent.id,
                user_id=agent.user_id,
                name=agent.name,
                model=agent.model,
                api_key=agent.api_key,
                db_session_func=self.db_session_func,
            )

            # 更新数据库状态
            agent.status = "wake"
            agent.last_active = datetime.now(timezone.utc)
            self.db.add(AgentStateHistory(
                agent_id=agent.id,
                old_status=old_status,
                new_status="wake",
                reason="agent connected",
            ))
            delivered_tasks = self.task_dispatch_service.deliver_pending_tasks_on_connect(
                target_agent_id=agent.id,
            )
            callback_deliveries = self._retry_pending_response_callbacks(agent)
            inbox_summary = self.get_task_inbox_summary(agent.id)
            self.db.commit()
            self.db.refresh(agent)
            runtime_agent = self.agent_factory.get(agent.user_id)
            if runtime_agent and inbox_summary["pending_task_count"] > 0:
                self._push_inbox_summary_to_agent(
                    target_agent=agent,
                    inbox_summary=inbox_summary,
                )
            return {
                "id": agent.id,
                "status": agent.status,
                "delivered_tasks": delivered_tasks,
                "callback_deliveries": callback_deliveries,
                "pending_task_count": inbox_summary["pending_task_count"],
                "pending_task_preview": inbox_summary["pending_task_preview"],
                "pending_system_message_count": (
                    runtime_agent.pending_system_message_count() if runtime_agent else 0
                ),
            }

        except HTTPException:
            raise
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    def use(self, req: AgentRequest):
        """调用已激活的运行时 Agent 执行一次用户请求。"""
        # 查询 agent 记录
        agent_record = self.db.query(AgentInfo).filter(
            AgentInfo.id == req.agent_id
        ).first()

        if not agent_record:
            raise HTTPException(status_code=404, detail="agent 不存在")

        # 更新状态为 active
        if agent_record.status == "wake":
            self.db.add(AgentStateHistory(
                agent_id=agent_record.id,
                old_status=agent_record.status,
                new_status="active",
                reason="agent started using",
            ))
            agent_record.status = "active"
            agent_record.last_active = datetime.now(timezone.utc)
            self.db.commit()

        # 调用 agent 执行
        agent = self.agent_factory.get(req.user_id)
        if not agent:
            raise HTTPException(status_code=404, detail="agent 未激活")

        result = agent.invoke(req.messages)

        # 使用完成后恢复为 wake 状态
        agent_record.status = "wake"
        agent_record.last_active = datetime.now(timezone.utc)
        self.db.add(AgentStateHistory(
            agent_id=agent_record.id,
            old_status="active",
            new_status="wake",
            reason="agent finished using",
        ))
        self.db.commit()

        return result

    def destroy(self, account_id):
        pass

    def check_permission(self, source_agent_id: int, target_agent_id: int, action: str) -> dict:
        """对外提供统一的权限判定结果，供接口层或任务流直接调用。"""
        # 业务层统一权限查询入口，后续接口/任务流直接复用这里的输出结构。
        decision = self.permission_service.check(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            action=action,
        )
        return {
            "action": decision.action,
            "result": decision.result,
            "reason": decision.reason,
            "relation": decision.relation,
            "source_agent_id": decision.source_agent_id,
            "target_agent_id": decision.target_agent_id,
        }

    def read_agent_permission(
        self,
        target_agent_id: int | None = None,
        target_agent_name: str | None = None,
    ) -> dict:
        """读取指定目标 Agent 的权限文件内容。"""
        resolved_target_id = self.resolve_agent_id(
            target_agent_id=target_agent_id,
            target_agent_name=target_agent_name,
        )
        summary = self.permission_file_service.summarize_permission_file(resolved_target_id)
        summary["target_agent_id"] = resolved_target_id
        return summary

    def list_my_tasks(
        self,
        target_agent_id: int,
        include_completed: bool = False,
    ) -> list[dict]:
        """查询指定 Agent 的任务收件箱。"""
        statuses = None
        if not include_completed:
            statuses = ["pending", "queued", "delivered", "waiting_user", "waiting_target_online"]
        tasks = self.task_service.list_tasks_for_agent(
            target_agent_id=target_agent_id,
            statuses=statuses,
        )
        return [self._task_to_dict(task) for task in tasks]

    def get_task_detail(self, task_id: int, requester_agent_id: int) -> dict:
        """读取某条任务详情及其事件流。"""
        task = self.task_service.get_task(task_id)
        if requester_agent_id not in {task.source_agent_id, task.target_agent_id}:
            raise HTTPException(status_code=403, detail="当前 Agent 无权查看该任务")

        events = self.task_service.list_task_events(task_id)
        detail = self._task_to_dict(task)
        detail["events"] = [
            {
                "event_id": event.id,
                "event_type": event.event_type,
                "event_payload": event.event_payload,
                "created_at": str(event.created_at),
            }
            for event in events
        ]
        return detail

    def get_task_inbox_summary(self, target_agent_id: int) -> dict:
        """返回目标 Agent 当前待处理任务的摘要。"""
        tasks = self.list_my_tasks(target_agent_id=target_agent_id, include_completed=False)
        preview = [
            {
                "task_id": task["task_id"],
                "task_type": task["task_type"],
                "status": task["status"],
                "source_agent_id": task["source_agent_id"],
                "requires_user_action": task["requires_user_action"],
            }
            for task in tasks[:5]
        ]
        return {
            "pending_task_count": len(tasks),
            "pending_task_preview": preview,
        }

    def request_connection(
        self,
        source_agent_id: int,
        target_agent_id: int,
        message: str | None = None,
    ) -> dict:
        """发起一条 Agent 连接请求，并按权限和目标状态决定后续动作。"""
        if source_agent_id == target_agent_id:
            raise HTTPException(status_code=400, detail="不能向自己发起连接请求")

        source_agent = self._get_agent_or_404(source_agent_id)
        target_agent = self._get_agent_or_404(target_agent_id)
        decision = self.permission_service.check(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            action="add_friend",
        )

        if decision.result == "deny":
            return {
                "action": "request_connection",
                "result": "deny",
                "reason": decision.reason,
                "source_agent_id": source_agent_id,
                "target_agent_id": target_agent_id,
            }

        if decision.result == "allow":
            self._establish_friend_connection(source_agent_id, target_agent_id)
            self.db.commit()
            return {
                "action": "request_connection",
                "result": "allow",
                "reason": "目标 Agent 允许直接建立连接",
                "source_agent_id": source_agent_id,
                "target_agent_id": target_agent_id,
                "target_status": target_agent.status,
            }

        dispatch_result = self.task_dispatch_service.dispatch_task(
            task_type="friend_request",
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            payload={
                "message": message,
                "source_agent_name": source_agent.name,
                "target_agent_name": target_agent.name,
            },
            requires_user_action=True,
            priority=10,
            permission_action="add_friend",
        )

        if dispatch_result.task_id is not None:
            self.graph_service.create_pending_request(
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                task_id=dispatch_result.task_id,
            )

        self.db.commit()
        return {
            "action": "request_connection",
            "result": "request",
            "task_id": dispatch_result.task_id,
            "delivery_status": dispatch_result.delivery_status,
            "target_status": dispatch_result.target_status,
            "reason": dispatch_result.reason,
            "source_agent_id": source_agent_id,
            "target_agent_id": target_agent_id,
        }

    def respond_connection_request(
        self,
        task_id: int,
        responder_agent_id: int,
        accepted: bool,
        response_message: str | None = None,
    ) -> dict:
        """处理目标 Agent 对连接申请的同意或拒绝。"""
        task = self.task_service.get_task(task_id)
        if task.task_type != "friend_request":
            raise HTTPException(status_code=400, detail="该任务不是连接申请任务")
        if task.target_agent_id != responder_agent_id:
            raise HTTPException(status_code=403, detail="当前 Agent 无权响应该连接申请")
        if task.status in {"accepted", "rejected", "done"}:
            raise HTTPException(status_code=400, detail="该连接申请已经处理完成")

        source_agent = self._get_agent_or_404(task.source_agent_id)
        responder_agent = self._get_agent_or_404(responder_agent_id)

        if accepted:
            self._establish_friend_connection(source_agent.id, responder_agent.id)
            self.graph_service.delete_pending_request(source_agent.id, responder_agent.id)
            self.task_service.update_task_status(
                task_id=task.id,
                status="accepted",
                event_type="accepted",
                event_payload={"message": response_message},
            )
            self.task_service.update_task_status(
                task_id=task.id,
                status="done",
                event_type="done",
                event_payload={"message": "friend request completed"},
            )
            response_dispatch = self.task_dispatch_service.dispatch_system_task(
                task_type="friend_request_response",
                source_agent_id=responder_agent.id,
                target_agent_id=source_agent.id,
                payload={
                    "accepted": True,
                    "message": response_message,
                    "friend_agent_id": responder_agent.id,
                },
            )
            callback_result = self._attempt_response_callback(
                target_agent=source_agent,
                response_task_id=response_dispatch.task_id,
                payload={
                    "request_task_id": task.id,
                    "accepted": True,
                    "message": response_message,
                    "source_agent_id": responder_agent.id,
                    "source_agent_name": responder_agent.name,
                    "target_agent_id": source_agent.id,
                    "target_agent_name": source_agent.name,
                    "friend_agent_id": responder_agent.id,
                    "friend_agent_name": responder_agent.name,
                },
            )
            self._push_runtime_feedback_to_agent(
                target_agent=source_agent,
                from_agent=responder_agent,
                event_type="friend_request_response",
                payload={
                    "accepted": True,
                    "message": response_message,
                    "friend_agent_id": responder_agent.id,
                    "friend_agent_name": responder_agent.name,
                },
            )
            self.db.commit()
            return {
                "task_id": task.id,
                "result": "accepted",
                "response_delivery_status": response_dispatch.delivery_status,
                "callback_status": callback_result["status"],
                "reason": "连接申请已同意，双方已建立好友关系",
            }

        self.graph_service.delete_pending_request(source_agent.id, responder_agent.id)
        self.task_service.update_task_status(
            task_id=task.id,
            status="rejected",
            event_type="rejected",
            event_payload={"message": response_message},
        )
        response_dispatch = self.task_dispatch_service.dispatch_system_task(
            task_type="friend_request_response",
            source_agent_id=responder_agent.id,
            target_agent_id=source_agent.id,
            payload={
                "accepted": False,
                "message": response_message,
                "friend_agent_id": responder_agent.id,
            },
        )
        callback_result = self._attempt_response_callback(
            target_agent=source_agent,
            response_task_id=response_dispatch.task_id,
            payload={
                "request_task_id": task.id,
                "accepted": False,
                "message": response_message,
                "source_agent_id": responder_agent.id,
                "source_agent_name": responder_agent.name,
                "target_agent_id": source_agent.id,
                "target_agent_name": source_agent.name,
                "friend_agent_id": responder_agent.id,
                "friend_agent_name": responder_agent.name,
            },
        )
        self._push_runtime_feedback_to_agent(
            target_agent=source_agent,
            from_agent=responder_agent,
            event_type="friend_request_response",
            payload={
                "accepted": False,
                "message": response_message,
                "friend_agent_id": responder_agent.id,
                "friend_agent_name": responder_agent.name,
            },
        )
        self.db.commit()
        return {
            "task_id": task.id,
            "result": "rejected",
            "response_delivery_status": response_dispatch.delivery_status,
            "callback_status": callback_result["status"],
            "reason": "连接申请已拒绝",
        }

    def resolve_agent_id(
        self,
        target_agent_id: int | None = None,
        target_agent_name: str | None = None,
    ) -> int:
        """按 ID 或名称解析目标 Agent 的唯一标识。"""
        if target_agent_id is not None:
            self._get_agent_or_404(target_agent_id)
            return target_agent_id

        if not target_agent_name:
            raise HTTPException(status_code=400, detail="必须提供 target_agent_id 或 target_agent_name")

        agent = (
            self.db.query(AgentInfo)
            .filter(AgentInfo.name == target_agent_name)
            .order_by(AgentInfo.id.asc())
            .first()
        )
        if not agent:
            raise HTTPException(status_code=404, detail=f"未找到名称为 {target_agent_name} 的 agent")
        return agent.id

    def list_connection_requests_for_tool(
        self,
        target_agent_id: int,
        include_waiting_online: bool = True,
    ) -> list[dict]:
        """供 RuntimeAgent 工具调用的连接申请查询入口。"""
        return self._list_connection_requests(
            target_agent_id=target_agent_id,
            include_waiting_online=include_waiting_online,
        )

    def _list_connection_requests(
        self,
        target_agent_id: int,
        include_waiting_online: bool,
    ) -> list[dict]:
        """按条件筛选目标 Agent 的连接申请任务。"""
        statuses = ["waiting_user", "delivered"]
        if include_waiting_online:
            statuses.append("waiting_target_online")

        tasks = (
            self.db.query(AgentTask)
            .filter(
                AgentTask.target_agent_id == target_agent_id,
                AgentTask.task_type == "friend_request",
                AgentTask.status.in_(statuses),
            )
            .order_by(AgentTask.created_at.asc())
            .all()
        )
        return [
            {
                "task_id": task.id,
                "source_agent_id": task.source_agent_id,
                "target_agent_id": task.target_agent_id,
                "status": task.status,
                "payload": task.payload,
            }
            for task in tasks
        ]

    def _establish_friend_connection(self, source_agent_id: int, target_agent_id: int) -> None:
        """建立双向好友关系，并同步到图数据库与权限文件。"""
        self.graph_service.create_friend_relation(source_agent_id, target_agent_id)
        self.permission_file_service.add_friend(source_agent_id, target_agent_id)
        self.permission_file_service.add_friend(target_agent_id, source_agent_id)

    def _get_agent_or_404(self, agent_id: int) -> AgentInfo:
        """读取指定 Agent，不存在时抛出 HTTP 404。"""
        agent = self.db.query(AgentInfo).filter(AgentInfo.id == agent_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"agent 不存在：{agent_id}")
        return agent

    def _push_runtime_feedback_to_agent(
        self,
        target_agent: AgentInfo,
        from_agent: AgentInfo,
        event_type: str,
        payload: dict,
    ) -> None:
        """如果目标 Agent 当前在线，则把系统反馈直接注入其运行时消息收件箱。"""
        runtime_agent = self.agent_factory.get(target_agent.user_id)
        if not runtime_agent:
            return

        runtime_agent.receive_system_message(
            message_type="system_event",
            event_type=event_type,
            payload=payload,
            from_agent_id=from_agent.id,
            from_agent_name=from_agent.name,
        )

    def _push_inbox_summary_to_agent(self, target_agent: AgentInfo, inbox_summary: dict) -> None:
        """在 Agent 上线后，把待处理任务摘要注入其内部消息上下文。"""
        runtime_agent = self.agent_factory.get(target_agent.user_id)
        if not runtime_agent:
            return

        runtime_agent.receive_system_message(
            message_type="system_event",
            event_type="task_inbox_summary",
            payload={
                "pending_task_count": inbox_summary["pending_task_count"],
                "pending_task_preview": inbox_summary["pending_task_preview"],
                "instruction": (
                    "请优先告诉用户当前有哪些待处理任务，尤其要指出需要用户处理的任务，"
                    "并提醒用户可以让你继续查看或处理这些任务。"
                ),
            },
            from_agent_name="system",
        )

    def _attempt_response_callback(self, target_agent: AgentInfo, response_task_id: int | None, payload: dict) -> dict:
        """尝试把响应任务回调到目标 Agent 对应的 User 系统。"""
        if response_task_id is None:
            return {"status": "not_created", "reason": "响应任务未创建"}

        response_task = self.task_service.get_task(response_task_id)
        self.task_service.update_task_status(
            task_id=response_task.id,
            status="pending_push",
            event_type="pending_push",
            event_payload={"reason": "准备尝试回调 User 系统"},
        )
        callback_result = self.callback_service.push_callback(
            agent=target_agent,
            event_type="friend_request_response",
            delivery_id=f"task-{response_task.id}",
            payload=payload,
        )
        if callback_result.success:
            self.task_service.update_task_status(
                task_id=response_task.id,
                status="push_success",
                event_type="push_success",
                event_payload={
                    "reason": callback_result.reason,
                    "status_code": callback_result.status_code,
                },
            )
            self.task_service.update_task_status(
                task_id=response_task.id,
                status="done",
                event_type="done",
                event_payload={"reason": "回调成功，响应任务完成"},
            )
            return {"status": "push_success", "reason": callback_result.reason}

        fallback_status = "waiting_target_online"
        if target_agent.callback_enabled and target_agent.callback_url:
            fallback_status = "push_failed"

        self.task_service.update_task_status(
            task_id=response_task.id,
            status=fallback_status,
            event_type=fallback_status,
            event_payload={
                "reason": callback_result.reason,
                "status_code": callback_result.status_code,
            },
        )
        return {"status": fallback_status, "reason": callback_result.reason}

    def _retry_pending_response_callbacks(self, target_agent: AgentInfo) -> list[dict]:
        """在目标 Agent 上线时补偿之前未完成的响应回调。"""
        tasks = (
            self.db.query(AgentTask)
            .filter(
                AgentTask.target_agent_id == target_agent.id,
                AgentTask.task_type == "friend_request_response",
                AgentTask.status.in_(["push_failed", "waiting_target_online", "pending_push"]),
            )
            .order_by(AgentTask.created_at.asc())
            .all()
        )
        results: list[dict] = []
        for task in tasks:
            callback_result = self.callback_service.push_callback(
                agent=target_agent,
                event_type="friend_request_response",
                delivery_id=f"task-{task.id}",
                payload=task.payload or {},
            )
            if callback_result.success:
                self.task_service.update_task_status(
                    task_id=task.id,
                    status="push_success",
                    event_type="push_success",
                    event_payload={
                        "reason": callback_result.reason,
                        "status_code": callback_result.status_code,
                    },
                )
                self.task_service.update_task_status(
                    task_id=task.id,
                    status="done",
                    event_type="done",
                    event_payload={"reason": "上线补偿回调成功"},
                )
                results.append({"task_id": task.id, "status": "push_success"})
            else:
                self.task_service.update_task_status(
                    task_id=task.id,
                    status="push_failed",
                    event_type="push_failed",
                    event_payload={
                        "reason": callback_result.reason,
                        "status_code": callback_result.status_code,
                    },
                )
                results.append({"task_id": task.id, "status": "push_failed"})
        return results

    @staticmethod
    def _task_to_dict(task: AgentTask) -> dict:
        """把任务 ORM 对象转换成适合返回给 Agent 的结构。"""
        return {
            "task_id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "source_agent_id": task.source_agent_id,
            "target_agent_id": task.target_agent_id,
            "payload": task.payload,
            "requires_user_action": task.requires_user_action,
            "priority": task.priority,
            "created_at": str(task.created_at),
            "updated_at": str(task.updated_at),
        }
