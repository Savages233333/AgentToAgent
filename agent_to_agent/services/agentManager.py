from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy.orm import Session
from agent_to_agent.models.agentInfo import AgentInfo
from agent_to_agent.models.agentStateHistory import AgentStateHistory
from agent_to_agent.factory.agentFactory import AgentFactory
from agent_to_agent.models.agentRequest import AgentRequest
from agent_to_agent.services.graphAgentService import GraphAgentNode, GraphAgentService
from agent_to_agent.services.permissionFileService import PermissionFileService
from agent_to_agent.services.permissionService import PermissionService

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
            self.db.commit()
            self.db.refresh(agent)
            return {"id": agent.id, "status": agent.status}

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
