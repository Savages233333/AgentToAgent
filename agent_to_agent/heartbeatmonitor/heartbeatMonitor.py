"""
Agent 心跳检测与生命周期管理服务。

定期检查 container 内的 agent：
1. wake 状态超过 WAKE_TIMEOUT 秒 → 自动销毁并标记为 sleep
2. active 状态超过 ACTIVE_TIMEOUT 秒未使用 → 自动销毁并标记为 sleep
"""

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional


from sqlalchemy import and_
from sqlalchemy.orm import Session

from agent_to_agent.models.agentInfo import AgentInfo
from agent_to_agent.models.agentStateHistory import AgentStateHistory
from agent_to_agent.factory.agentFactory import AgentFactory


class HeartbeatMonitor:
    """心跳检测器，单例模式运行后台监控任务。"""

    _instance: Optional['HeartbeatMonitor'] = None
    _lock = threading.Lock()

    # 配置参数（已优化安全边际）
    WAKE_TIMEOUT = 600  # wake 状态最大持续时间（秒），改为 10 分钟
    ACTIVE_TIMEOUT = 1800  # active 状态闲置超时时间（秒），保持 30 分钟
    CHECK_INTERVAL = 15  # 检查间隔（秒），改为 15 秒提高精度

    def __new__(cls, db_session_func: Optional[Callable[[], Session]] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.db_session_func = db_session_func
                    cls._instance.running = False
                    cls._instance.monitor_thread: Optional[threading.Thread] = None
        return cls._instance

    def _get_db_session(self) -> Session:
        """从生成器获取数据库会话（处理 FastAPI 的 get_db）。"""
        if not self.db_session_func:
            raise RuntimeError("数据库会话工厂未初始化")

        result = self.db_session_func()

        # 如果是生成器（FastAPI 的 get_db），调用 next() 获取 session
        if hasattr(result, '__next__'):
            try:
                return next(result)
            except StopIteration:
                raise RuntimeError("数据库会话生成器异常")

        # 如果已经是 session，直接返回
        return result

    def start(self):
        """启动后台监控线程。"""
        if self.running:
            print("[HeartbeatMonitor] 监控已在运行")
            return

        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="heartbeat-monitor"
        )
        self.monitor_thread.start()
        print(
            f"[HeartbeatMonitor] 监控已启动 "
            f"(wake_timeout={self.WAKE_TIMEOUT}s, active_timeout={self.ACTIVE_TIMEOUT}s, "
            f"check_interval={self.CHECK_INTERVAL}s)"
        )

    def stop(self):
        """停止后台监控线程。"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        print("[HeartbeatMonitor] 监控已停止")

    def _monitor_loop(self):
        """监控主循环。"""
        while self.running:
            try:
                self._check_and_cleanup_agents()
            except Exception as e:
                print(f"[HeartbeatMonitor] 检查异常：{e}")

            # 等待下一次检查
            for _ in range(self.CHECK_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

    def _check_and_cleanup_agents(self):
        """检查并清理超时的 agent。"""
        if not self.db_session_func:
            print("[HeartbeatMonitor] 数据库会话未初始化")
            return

        db: Session = self._get_db_session()
        try:
            now = datetime.now(timezone.utc)
            wake_threshold = now - timedelta(seconds=self.WAKE_TIMEOUT)
            active_threshold = now - timedelta(seconds=self.ACTIVE_TIMEOUT)

            # 查找 wake 状态超时的 agent
            wake_agents = db.query(AgentInfo).filter(
                and_(
                    AgentInfo.status == "wake",
                    AgentInfo.last_active.isnot(None),
                    AgentInfo.last_active < wake_threshold
                )
            ).all()

            for agent in wake_agents:
                self._destroy_agent(db, agent, "wake_timeout",
                                    f"wake 状态超过 {self.WAKE_TIMEOUT}秒")

            # 查找 active 状态闲置超时的 agent
            active_agents = db.query(AgentInfo).filter(
                and_(
                    AgentInfo.status == "active",
                    AgentInfo.last_active.isnot(None),
                    AgentInfo.last_active < active_threshold
                )
            ).all()

            for agent in active_agents:
                self._destroy_agent(db, agent, "active_timeout",
                                    f"active 状态闲置超过 {self.ACTIVE_TIMEOUT}秒")

            if wake_agents or active_agents:
                db.commit()
                print(
                    f"[HeartbeatMonitor] 本次清理："
                    f"{len(wake_agents)} 个 wake 超时，"
                    f"{len(active_agents)} 个 active 超时"
                )

        except Exception as e:
            db.rollback()
            print(f"[HeartbeatMonitor] 检查失败：{e}")
        finally:
            # 确保关闭会话（重要！）
            db.close()
            print("[HeartbeatMonitor] 数据库会话已关闭")

    def _destroy_agent(self, db: Session, agent: AgentInfo, reason: str, detail: str):
        """销毁指定 agent，从 container 移除并更新数据库状态。"""
        try:
            # 双重检查：重新获取最新状态（防止并发）
            fresh_agent = db.query(AgentInfo).filter(
                AgentInfo.id == agent.id
            ).with_for_update().first()  # ← 添加行级锁

            if not fresh_agent:
                print(f"[HeartbeatMonitor] agent(id={agent.id}) 不存在，跳过销毁")
                return

            # 检查是否已被其他进程处理
            if fresh_agent.status == "sleep":
                print(f"[HeartbeatMonitor] agent(id={agent.id}) 已是 sleep 状态，跳过")
                return

            # 重新计算阈值（根据最新状态）
            now = datetime.now(timezone.utc)
            threshold = now - timedelta(
                seconds=self.WAKE_TIMEOUT if fresh_agent.status == "wake"
                else self.ACTIVE_TIMEOUT
            )

            # 再次检查是否真的超时
            if not fresh_agent.last_active or fresh_agent.last_active >= threshold:
                print(
                    f"[HeartbeatMonitor] agent(id={agent.id}) 已恢复活跃 "
                    f"(last_active={fresh_agent.last_active}), 跳过销毁"
                )
                return

            # 从 factory container 中移除
            factory = AgentFactory()
            if factory.exists(fresh_agent.user_id):
                factory.remove(fresh_agent.user_id)
                print(
                    f"[HeartbeatMonitor] 已从 container 移除 "
                    f"agent(user_id={fresh_agent.user_id}, id={fresh_agent.id})"
                )

            # 更新数据库状态
            old_status = fresh_agent.status
            fresh_agent.status = "sleep"

            # 记录状态变更历史
            history = AgentStateHistory(
                agent_id=fresh_agent.id,
                old_status=old_status,
                new_status="sleep",
                node="auto_cleanup",
                reason=detail,
            )
            db.add(history)

            print(
                f"[HeartbeatMonitor] agent(id={fresh_agent.id}, user_id={fresh_agent.user_id}) "
                f"已从 {old_status} → sleep（原因：{detail}）"
            )

        except Exception as e:
            print(f"[HeartbeatMonitor] 销毁 agent 失败：{e}")
            raise
