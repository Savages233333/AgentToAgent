from fastapi import HTTPException
from sqlalchemy.orm import Session
from agent_to_agent.models.agentInfo import AgentInfo
from agent_to_agent.models.agentStateHistory import AgentStateHistory
from agent_to_agent.factory.agentFactory import AgentFactory


class AgentManager:
    def __init__(self, db: Session):
        self.db = db
        self.agent_factory = AgentFactory()

    def agentRegister(self, req):
        """
        注册新 agent。

        向 agents 表写入一条记录，name 取 req.model_name，
        model 固定为 qwen3-max，status 初始化为 new，
        同时写入首条 AgentStateHistory（old_status=None → new）。
        """
        agent = AgentInfo(
            user_id=req.user_id,
            name=req.model_name,
            model="qwen3-max",
            api_key=req.api_key,
            status="new",
        )
        self.db.add(agent)
        self.db.flush()

        history = AgentStateHistory(
            agent_id=agent.id,
            old_status=None,
            new_status="new",
            reason="agent registered",
        )
        self.db.add(history)
        self.db.commit()
        self.db.refresh(agent)
        return {"id": agent.id, "status": agent.status}

    def connect(self, req):
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
                raise HTTPException(status_code=404, detail="agent没有被注册喔")

            old_status = agent.status

            # 工厂创建运行时 Agent 存入内存容器
            self.agent_factory.create(
                agent_id=agent.id,
                user_id=agent.user_id,
                name=agent.name,
                model=agent.model,
                api_key=agent.api_key,
            )

            # 更新数据库状态
            agent.status = "wake"
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

    def use(self, req):
        try :
            pass
        except HTTPException:
            raise
        graph = self.agent_factory.get(req.user_id)
        return graph.invoke(req.message)

    def destroy(self, account_id):
        pass
