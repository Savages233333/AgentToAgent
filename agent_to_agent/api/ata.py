from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from agent_to_agent.models import get_db
from agent_to_agent.services.agentManager import AgentManager
from agent_to_agent.models.agentRequest import AgentRequest
from agent_to_agent.models.agentConnectionRequest import (
    AgentConnectionRequest,
    AgentConnectionResponseRequest,
)

router = APIRouter()





@router.post("/agentRegister")
def agentRegister(req: AgentRequest, db: Session = Depends(get_db)):
    """
    注册 agent。->（无状态）-> new

    将 model_name 写入 agents 表的 name 字段，model 固定为 qwen3-max，
    status 初始化为 new，同时写入一条 AgentStateHistory 记录。
    """
    return AgentManager(db).agentRegister(req)


@router.post("/connect")
def connect(req: AgentRequest, db: Session = Depends(get_db)):
    """
    建立连接，唤醒 agent。-> new/sleep -> wake

    原子操作（失败自动回滚）：
    1. 校验 agent 存在且状态为 new 或 sleep
    2. 通过 AgentFactory 在内存容器中创建 RuntimeAgent 实例
    3. 将数据库中 agent 状态改为 wake，并写入 AgentStateHistory 记录
    """
    return AgentManager(db).connect(req)


@router.post("/use")
def use(req: AgentRequest, db: Session = Depends(get_db)):
    """向处于 wake 状态的 agent 发送消息并返回推理结果。"""
    return AgentManager(db).use(req)


@router.post("/connection/request")
def request_connection(req: AgentConnectionRequest, db: Session = Depends(get_db)):
    """发起 Agent 连接申请，并按权限与生命周期状态处理。"""
    return AgentManager(db).request_connection(
        source_agent_id=req.source_agent_id,
        target_agent_id=req.target_agent_id,
        message=req.message,
    )


@router.post("/connection/respond")
def respond_connection(req: AgentConnectionResponseRequest, db: Session = Depends(get_db)):
    """处理目标 Agent 对连接申请的同意或拒绝。"""
    return AgentManager(db).respond_connection_request(
        task_id=req.task_id,
        responder_agent_id=req.responder_agent_id,
        accepted=req.accepted,
        response_message=req.response_message,
    )


@router.get("/connection/requests/{target_agent_id}")
def list_connection_requests(target_agent_id: int, db: Session = Depends(get_db)):
    """查询目标 Agent 当前待处理的连接申请。"""
    return AgentManager(db).list_connection_requests(target_agent_id)


@router.post("/destroy/{account_id}")
def destroy(account_id: int, db: Session = Depends(get_db)):
    """注销 agent。仅允许 wake 或 new 状态下执行。-> destroy"""
    return AgentManager(db).destroy(account_id)
