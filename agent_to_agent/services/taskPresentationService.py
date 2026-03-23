from agent_to_agent.models.agentTask import AgentTask


class TaskPresentationService:
    """把任务对象转换成更适合 Agent 和前端消费的展示结构。"""

    def build_task_view(self, task: AgentTask) -> dict:
        """生成统一的任务展示摘要。"""
        payload = task.payload or {}
        title, summary, action_hint = self._build_copy(task)
        return {
            "title": title,
            "summary": summary,
            "action_hint": action_hint,
            "task_group": task.task_group,
            "requires_user_action": task.requires_user_action,
            "priority": task.priority,
            "source_agent_name": payload.get("source_agent_name"),
            "target_agent_name": payload.get("target_agent_name"),
        }

    def _build_copy(self, task: AgentTask) -> tuple[str, str, str]:
        """按任务类型生成稳定的人类可读摘要。"""
        payload = task.payload or {}
        source_name = payload.get("source_agent_name") or f"Agent {task.source_agent_id}"
        message = payload.get("message")

        if task.task_type == "friend_request":
            summary = f"{source_name} 想与你建立好友关系"
            if message:
                summary = f"{summary}。附言：{message}"
            return (
                "新的好友申请",
                summary,
                "你可以让我查看详情、同意或拒绝这条申请。",
            )

        if task.task_type == "friend_request_response":
            accepted = payload.get("accepted")
            if accepted:
                return (
                    "好友申请已通过",
                    f"{source_name} 已同意你的好友申请。",
                    "你可以让我继续查看最新好友关系或后续任务。",
                )
            return (
                "好友申请被拒绝",
                f"{source_name} 拒绝了你的好友申请。",
                "你可以让我查看原因，或继续处理其他任务。",
            )

        return (
            task.task_type,
            f"你有一条类型为 {task.task_type} 的任务待处理。",
            "你可以让我查看这条任务的详情。",
        )
