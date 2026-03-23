import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from agent_to_agent.models.agentInfo import AgentInfo


@dataclass(slots=True)
class CallbackResult:
    success: bool
    status_code: int | None
    reason: str


class AgentCallbackService:
    def build_payload(self, agent: AgentInfo, event_type: str, delivery_id: str, payload: dict) -> dict:
        """构造发送给 User 系统的标准回调负载。"""
        return {
            "event_type": event_type,
            "delivery_id": delivery_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent.id,
            "user_id": agent.user_id,
            "payload": payload,
        }

    def push_callback(self, agent: AgentInfo, event_type: str, delivery_id: str, payload: dict) -> CallbackResult:
        """向目标 Agent 对应的 User 系统回调接口发送事件。"""
        if not agent.callback_enabled or not agent.callback_url:
            return CallbackResult(
                success=False,
                status_code=None,
                reason="目标 Agent 未配置可用的回调地址",
            )

        body = self.build_payload(agent, event_type=event_type, delivery_id=delivery_id, payload=payload)
        raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Agent-Event-Type": event_type,
            "X-Agent-Delivery-Id": delivery_id,
        }
        if agent.callback_secret:
            headers["X-Agent-Signature"] = self._sign_body(agent.callback_secret, raw_body)

        try:
            response = requests.post(
                agent.callback_url,
                data=raw_body,
                headers=headers,
                timeout=agent.callback_timeout_seconds or 5,
            )
        except requests.RequestException as exc:
            return CallbackResult(
                success=False,
                status_code=None,
                reason=f"回调请求失败：{exc}",
            )

        if response.status_code in {200, 201, 202}:
            return CallbackResult(
                success=True,
                status_code=response.status_code,
                reason="回调成功",
            )

        return CallbackResult(
            success=False,
            status_code=response.status_code,
            reason=f"回调返回非成功状态码：{response.status_code}",
        )

    @staticmethod
    def _sign_body(secret: str, raw_body: bytes) -> str:
        """使用 callback_secret 对请求体做 HMAC-SHA256 签名。"""
        return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
