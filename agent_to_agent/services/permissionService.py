from dataclasses import dataclass

from sqlalchemy.orm import Session

from agent_to_agent.models.agentInfo import AgentInfo
from agent_to_agent.services.graphAgentService import GraphAgentService
from agent_to_agent.services.permissionFileService import PermissionFileService


@dataclass(slots=True)
class PermissionDecision:
    action: str
    result: str
    reason: str
    relation: str
    source_agent_id: int
    target_agent_id: int


class PermissionService:
    def __init__(
        self,
        db: Session,
        permission_file_service: PermissionFileService | None = None,
        graph_service: GraphAgentService | None = None,
    ) -> None:
        """初始化权限引擎所需的数据源和依赖服务。"""
        self.db = db
        self.permission_file_service = permission_file_service or PermissionFileService()
        self.graph_service = graph_service or GraphAgentService()

    def check(
        self,
        source_agent_id: int,
        target_agent_id: int,
        action: str,
    ) -> PermissionDecision:
        """统一计算某个来源 Agent 对目标 Agent 执行指定动作的权限结果。"""
        # 统一权限入口：
        # 先拿到源/目标 Agent，再读取目标侧权限文件，最后结合关系给出 allow/deny/request。
        source_agent = self._get_agent(source_agent_id)
        target_agent = self._get_agent(target_agent_id)
        target_permission = self.permission_file_service.load_permission_file(target_agent_id)
        relation = self._resolve_relation(source_agent, target_agent, target_permission)

        if action == "add_friend":
            result, reason = self._check_add_friend(
                source_agent=source_agent,
                target_permission=target_permission,
                relation=relation,
            )
        elif action == "send_message":
            result, reason = self._check_send_message(
                target_permission=target_permission,
                relation=relation,
            )
        elif action == "assign_task":
            result, reason = self._check_assign_task(
                target_permission=target_permission,
                relation=relation,
            )
        elif action == "wake_and_deliver_task":
            result, reason = self._check_wake_and_deliver_task(
                target_permission=target_permission,
                relation=relation,
            )
        else:
            raise ValueError(f"不支持的权限动作：{action}")

        return PermissionDecision(
            action=action,
            result=result,
            reason=reason,
            relation=relation,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
        )

    def _get_agent(self, agent_id: int) -> AgentInfo:
        """从数据库读取指定 Agent，不存在则抛错。"""
        agent = self.db.query(AgentInfo).filter(AgentInfo.id == agent_id).first()
        if not agent:
            raise ValueError(f"agent 不存在：{agent_id}")
        return agent

    def _resolve_relation(
        self,
        source_agent: AgentInfo,
        target_agent: AgentInfo,
        target_permission: dict,
    ) -> str:
        """识别来源 Agent 与目标 Agent 的关系类型。"""
        if source_agent.id == target_agent.id:
            return "self"

        friends = set(target_permission.get("relations", {}).get("friends", []))
        blocked = set(target_permission.get("relations", {}).get("blocked", []))

        if source_agent.id in blocked:
            return "blocked"

        if source_agent.id in friends:
            return "friend"

        # 关系识别优先级：
        # 1. 目标权限文件中的显式关系
        # 2. 图数据库中的 FRIEND / REPORTS_TO
        # 3. MySQL 中的 manager_agent_id 回退判断
        if self._safe_graph_has_friend(source_agent.id, target_agent.id):
            return "friend"

        if self._safe_graph_is_manager(source_agent.id, target_agent.id):
            return "manager"

        if self._safe_graph_is_manager(target_agent.id, source_agent.id):
            return "subordinate"

        if target_agent.manager_agent_id == source_agent.id:
            return "manager"

        if source_agent.manager_agent_id == target_agent.id:
            return "subordinate"

        return "stranger"

    def _check_add_friend(
        self,
        source_agent: AgentInfo,
        target_permission: dict,
        relation: str,
    ) -> tuple[str, str]:
        """判断来源 Agent 是否可以向目标 Agent 发起好友连接。"""
        if relation == "blocked":
            return "deny", "目标 Agent 已拉黑来源 Agent"

        if relation == "friend":
            return "allow", "双方已经是好友关系"

        friendship = target_permission.get("friendship", {})
        # 将来源 Agent 转成一组可匹配的策略 key，便于权限文件按 id / user / role / relation 配置规则。
        source_keys = self._build_match_keys(source_agent, relation)

        if self._matches_policy(friendship.get("deny_from", []), source_keys):
            return "deny", "目标 Agent 的好友策略拒绝该来源"

        if self._matches_policy(friendship.get("allow_from", []), source_keys):
            return "allow", "目标 Agent 的好友策略允许该来源"

        if self._matches_policy(friendship.get("require_request_from", []), source_keys):
            return "request", "目标 Agent 要求先发送好友申请"

        policy = target_permission.get("default_relation_policy", "request")
        if policy not in {"allow", "deny", "request"}:
            policy = "request"
        return policy, "根据目标 Agent 的默认好友策略判定"

    def _check_send_message(self, target_permission: dict, relation: str) -> tuple[str, str]:
        """判断来源 Agent 是否可以向目标 Agent 直接发送消息。"""
        if relation == "blocked":
            return "deny", "目标 Agent 已拉黑来源 Agent"

        message = target_permission.get("message", {})
        if relation == "friend":
            allowed = message.get("allow_direct_message_from_friends", False)
            return self._bool_to_result(allowed, "好友消息策略")

        if relation == "manager":
            allowed = message.get("allow_direct_message_from_manager", False)
            return self._bool_to_result(allowed, "上级消息策略")

        if relation == "subordinate":
            allowed = message.get("allow_direct_message_from_subordinates", False)
            return self._bool_to_result(allowed, "下级消息策略")

        return "request", "陌生关系默认需要更高层业务策略裁定"

    def _check_assign_task(self, target_permission: dict, relation: str) -> tuple[str, str]:
        """判断来源 Agent 是否可以向目标 Agent 直接派发任务。"""
        if relation == "blocked":
            return "deny", "目标 Agent 已拉黑来源 Agent"

        task = target_permission.get("task", {})
        if relation == "manager":
            allowed = task.get("allow_task_from_manager", False)
            return self._bool_to_result(allowed, "上级派任务策略")

        if relation == "subordinate":
            allowed = task.get("allow_task_from_subordinates", False)
            return self._bool_to_result(allowed, "下级派任务策略")

        if relation == "friend":
            allowed = task.get("allow_task_from_friends", False)
            return self._bool_to_result(allowed, "好友派任务策略")

        return "deny", "陌生关系默认不允许直接派发任务"

    def _check_wake_and_deliver_task(self, target_permission: dict, relation: str) -> tuple[str, str]:
        """判断来源 Agent 是否可以唤醒目标 Agent 并直接投递任务。"""
        # 自动唤醒前必须先满足“允许派任务”，否则不应直接绕过目标侧策略。
        assign_result, assign_reason = self._check_assign_task(target_permission, relation)
        if assign_result != "allow":
            return assign_result, assign_reason

        auto_wake = target_permission.get("task", {}).get("allow_auto_wake_for_task", False)
        if auto_wake:
            return "allow", "目标 Agent 允许自动唤醒并接收任务"
        return "request", "目标 Agent 不允许自动唤醒，需等待其上线处理"

    @staticmethod
    def _build_match_keys(source_agent: AgentInfo, relation: str) -> set[str]:
        """把来源 Agent 转换成权限策略可匹配的 key 集合。"""
        # 权限文件中的策略项可使用多种维度匹配来源：
        # "*"、agent_id、user_id、role_type、relation。
        keys = {
            "*",
            str(source_agent.id),
            f"user:{source_agent.user_id}",
            f"role:{source_agent.role_type or 'staff'}",
            f"relation:{relation}",
        }
        return keys

    @staticmethod
    def _matches_policy(policy_items: list, source_keys: set[str]) -> bool:
        """判断来源 key 集合是否命中权限文件中的某个策略项。"""
        normalized = {str(item) for item in policy_items}
        return bool(normalized & source_keys)

    @staticmethod
    def _bool_to_result(allowed: bool, policy_name: str) -> tuple[str, str]:
        """把布尔策略结果转成统一的 allow/deny 输出。"""
        if allowed:
            return "allow", f"{policy_name}允许"
        return "deny", f"{policy_name}不允许"

    def _safe_graph_has_friend(self, source_agent_id: int, target_agent_id: int) -> bool:
        """安全查询图数据库中的好友关系，失败时回退为 False。"""
        try:
            return self.graph_service.has_friend_relation(source_agent_id, target_agent_id)
        except Exception:
            # 图数据库不可用时不阻断主流程，回落到权限文件和 MySQL 关系。
            return False

    def _safe_graph_is_manager(self, manager_agent_id: int, subordinate_agent_id: int) -> bool:
        """安全查询图数据库中的上下级关系，失败时回退为 False。"""
        try:
            return self.graph_service.is_manager_of(manager_agent_id, subordinate_agent_id)
        except Exception:
            # 图数据库不可用时不阻断主流程，回落到 manager_agent_id 判断。
            return False
