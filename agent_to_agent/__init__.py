"""
Agent-to-Agent 系统核心模块。

提供 agent 创建、管理、通信和心跳检测等基础能力。
"""

from datetime import datetime

# 导入心跳监控器（确保应用启动时初始化）
from agent_to_agent.heartbeatmonitor.heartbeatMonitor import HeartbeatMonitor

__version__ = "0.1.0"
__all__ = ["HeartbeatMonitor", "datetime"]