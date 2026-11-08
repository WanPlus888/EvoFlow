"""运营大脑缺口匹配中间件：意图→候选旁路（装配在 ToolApprovalMiddleware 之前）。

只读注入：在真实用户回合末尾追加一条命名 HumanMessage（``<ops_brain_gap_match>`` 块），
告知本回合意图命中的白名单工具候选与执行闸规则。边界（与
``evoflow.collab.ops_brain_gap_match`` 一致）：

- 自己不 invoke 任何工具、不产出确认卡——确认卡由 ToolApprovalMiddleware 在
  tool call 时按风险表弹出（不绕过 approval middleware）；
- 候选白名单取 ``request.tools``（本回合实际绑定的工具 = AgentConfig.tools ∩ 会话门禁，
  含 fail-closed 剥离结果），denylist / 高危 MCP 由匹配器硬排除；
- ``OPS_BRAIN_GAP_MATCH=0`` / 无人值守自动化 / 任何内部异常 → 整段静默不注入。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from evoflow.agents.automation_runtime import is_unattended_automation
from evoflow.agents.message_analysis_utils import is_real_user_message, should_inject_turn_tail
from evoflow.collab.ops_brain_gap_match import (
    build_catalog_from_tools,
    gap_match_enabled,
    match_registered_tools,
)

logger = logging.getLogger(__name__)

_GAP_MATCH_MESSAGE_NAME = "ops_brain_gap_match"
_GAP_MATCH_BLOCK_TAG = "ops_brain_gap_match"

_RISK_LABELS = {"auto": "只读，可直接调用", "session": "会话级授权", "confirm": "需确认卡，用户确认后才执行"}


def _latest_user_intent(messages: list[BaseMessage]) -> str:
    """最近一条真实用户消息文本（多模态块取 text 部分；截断 500 字）。"""
    for msg in reversed(messages):
        if not isinstance(msg, HumanMessage):
            continue
        if getattr(msg, "name", None) == _GAP_MATCH_MESSAGE_NAME:
            continue
        if not is_real_user_message(msg):
            continue
        content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif isinstance(block, str):
                    parts.append(block)
            content = "\n".join(parts)
        text = str(content).strip()
        return text[:500] if text else ""
    return ""


def build_gap_match_block(*, intent_text: str, allowed_tools: set[str], tools_for_catalog) -> str:
    """意图 + 白名单 → ``<ops_brain_gap_match>`` 提示块；无候选返回空串。"""
    catalog = build_catalog_from_tools(tools_for_catalog)
    matches = match_registered_tools(
        intent_text=intent_text,
        allowed_tools=allowed_tools,
        catalog=catalog,
    )
    if not matches:
        return ""
    lines = [
        f"<{_GAP_MATCH_BLOCK_TAG}>",
        "本回合意图命中的已授权工具候选（按相关度，仅限白名单内）：",
    ]
    for m in matches:
        label = _RISK_LABELS.get(m.risk, m.risk)
        lines.append(f"- {m.tool_name}（{label}）：{m.reason}")
    lines.extend([
        "规则：只读候选可直接调用；confirm 级发起 tool call 时会弹确认卡，须用户确认后才执行；",
        "未列出的工具不得调用；若无候选，按占位文案自然语言说明并建议转人工，禁止用 bash 等方式替代。",
        f"</{_GAP_MATCH_BLOCK_TAG}>",
    ])
    return "\n".join(lines)


def _is_gap_match_message(msg: BaseMessage) -> bool:
    return isinstance(msg, (SystemMessage, HumanMessage, ToolMessage)) and getattr(msg, "name", None) == _GAP_MATCH_MESSAGE_NAME


def _strip_gap_match_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    return [m for m in messages if not _is_gap_match_message(m)]


def _messages_from_request(request: ModelRequest) -> list[BaseMessage]:
    state_msgs: list = list((request.state or {}).get("messages") or []) if isinstance(request.state, dict) else []
    req_msgs: list = list(request.messages or []) if getattr(request, "messages", None) else []
    raw = state_msgs if len(state_msgs) >= len(req_msgs) else req_msgs
    return [m for m in raw if isinstance(m, BaseMessage)]


def _allowed_tool_names(request: ModelRequest) -> set[str]:
    """本回合实际绑定的工具名（AgentConfig ∩ 会话门禁后的实时白名单）。"""
    tools = getattr(request, "tools", None) or []
    names = {str(getattr(t, "name", "") or "").strip().lower() for t in tools}
    return {n for n in names if n}


class OpsBrainGapMatchMiddleware(AgentMiddleware[AgentState]):
    """意图→候选旁路：只读提示注入，绝不 invoke / 绕闸。"""

    def _apply_block(self, request: ModelRequest, block: str) -> ModelRequest:
        messages = _strip_gap_match_messages(_messages_from_request(request))
        if len(messages) != len(_messages_from_request(request)):
            request = request.override(messages=messages)
        if not block:
            return request
        # 只在真实用户回合末尾注入（工具循环续轮不重复贴，避免被当成新用户轮）
        if not should_inject_turn_tail(messages):
            return request
        hint = HumanMessage(content=block.strip(), name=_GAP_MATCH_MESSAGE_NAME)
        return request.override(messages=[*messages, hint])

    def _build_request_block(self, request: ModelRequest) -> str:
        if not gap_match_enabled():
            return ""
        state_msgs: list = list((request.state or {}).get("messages") or []) if isinstance(request.state, dict) else []
        if not should_inject_turn_tail(state_msgs):
            return ""
        messages = _messages_from_request(request)
        intent = _latest_user_intent(messages)
        if not intent:
            return ""
        allowed = _allowed_tool_names(request)
        if not allowed:
            return ""
        return build_gap_match_block(
            intent_text=intent,
            allowed_tools=allowed,
            tools_for_catalog=getattr(request, "tools", None) or [],
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelCallResult],
    ) -> ModelCallResult:
        if is_unattended_automation(getattr(request, "runtime", None)):
            return handler(request)
        try:
            request = self._apply_block(request, self._build_request_block(request))
        except Exception:
            logger.debug("ops brain gap match inject failed (non-fatal)", exc_info=True)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelCallResult]],
    ) -> ModelCallResult:
        if is_unattended_automation(getattr(request, "runtime", None)):
            return await handler(request)
        try:
            request = self._apply_block(request, self._build_request_block(request))
        except Exception:
            logger.debug("ops brain gap match inject failed (non-fatal)", exc_info=True)
        return await handler(request)
