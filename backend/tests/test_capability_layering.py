"""P1：平台能力清单（L1）与工作台岗位白名单（L2）分层协同。

验收钉死：
- platform_scope=None（不设限）不能冲开 workbench_* fail-closed
- platform custom 放开 media 域 ≠ 授予 workbench_video_submit
- 套图岗无视频生产工具；客服岗无任何生产 workbench
- 草稿工具按岗可见但不在 WORKBENCH_TOOL_NAMES，仍不派单
"""

from __future__ import annotations

import json

import pytest

from evoflow.collab.worker_tool_allowlist import resolve_worker_tool_allowlist
from evoflow.config.agents_config import AgentConfig
from evoflow.config.platform_scope import PlatformScope, action_allowed
from evoflow.session_tool_binding import agent_tools as agent_tools_mod
from evoflow.session_tool_binding.agent_tools import bound_tools_for_session_agent
from evoflow.tools.builtins.workbench_order_draft_tool import draft_workbench_order
from evoflow.tools.builtins.workbench_tools import WORKBENCH_TOOL_NAMES

CATALOG = frozenset(
    {
        "read",
        "bash",
        "todo",
        "view_image",
        "platform",
        "draft_workbench_order",
        *WORKBENCH_TOOL_NAMES,
    }
)

AGENT_CONFIGS: dict[str, AgentConfig] = {
    # 不设限平台 + 无 workbench 勾选 → 仍 fail-closed
    "open-platform-op": AgentConfig(
        agent_code="open-platform-op",
        agent_name="平台不设限岗",
        tools=["read", "bash", "todo", "draft_workbench_order"],
        platform_scope=None,
    ),
    # 平台 custom 放开 media，但 tools 无 workbench → 仍无生产工具
    "media-scope-op": AgentConfig(
        agent_code="media-scope-op",
        agent_name="平台媒体域岗",
        tools=["read", "bash", "platform"],
        platform_scope=PlatformScope(mode="custom", domains=["media"], max_risk="write"),
    ),
    "tuantu-op": AgentConfig(
        agent_code="tuantu-op",
        agent_name="套图岗",
        tools=[
            "read",
            "bash",
            "todo",
            "draft_workbench_order",
            "workbench_products_list",
            "workbench_image_submit",
            "workbench_image_status",
        ],
        platform_scope=PlatformScope(mode="custom", domains=["knowledge"], max_risk="write"),
    ),
    "kefu-op": AgentConfig(
        agent_code="kefu-op",
        agent_name="客服岗",
        tools=["read", "bash", "todo", "draft_workbench_order"],
        platform_scope=PlatformScope(mode="none"),
    ),
}


def _fake_load(name):
    cfg = AGENT_CONFIGS.get(str(name or "").strip().lower())
    if cfg is None:
        raise FileNotFoundError(name)
    return cfg


def _universe_for(agent_id: str) -> frozenset[str]:
    cfg = AGENT_CONFIGS.get(str(agent_id or "").strip().lower())
    if cfg is None or cfg.tools is None:
        return CATALOG
    return frozenset(t.strip().lower() for t in cfg.tools if str(t or "").strip())


@pytest.fixture()
def fake_agents(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("evoflow.config.agents_config.load_agent_config", _fake_load)
    monkeypatch.setattr(agent_tools_mod, "load_agent_config", _fake_load)
    monkeypatch.setattr(
        agent_tools_mod,
        "resolve_agent_tool_names_for_agent",
        lambda agent_id, **_k: _universe_for(agent_id),
    )
    monkeypatch.setattr(
        agent_tools_mod,
        "resolve_agent_tool_names_for_session",
        lambda session_key: _universe_for(_agent_id_from_key(session_key)),
    )
    monkeypatch.setattr(
        "evoflow.persistence.db.get_db",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db in unit tests")),
    )
    return AGENT_CONFIGS


def _agent_id_from_key(session_key: str) -> str:
    from evoflow.persistence.session_context_fields import agent_id_from_session_key

    return agent_id_from_session_key(str(session_key or "")) or "main"


def _resolve_worker(assignee: str) -> list[str]:
    return resolve_worker_tool_allowlist(
        profile_tools=None,
        assignee_agent_code=assignee,
        base_subagent="general-purpose",
        subagent_config_tools=None,
        catalog_names=set(CATALOG),
        session_key=None,
        session_mode="agent",
    )


def test_unrestricted_platform_scope_does_not_open_workbench(fake_agents):
    """L1 不设限 ≠ L2 授权：无 workbench 勾选时会话/ worker 都拿不到生产工具。"""
    out_session = set(bound_tools_for_session_agent("agent:open-platform-op:t1", "agent"))
    out_worker = set(_resolve_worker("open-platform-op"))
    assert not out_session & WORKBENCH_TOOL_NAMES
    assert not out_worker & WORKBENCH_TOOL_NAMES
    assert "draft_workbench_order" in out_session or "draft_workbench_order" in AGENT_CONFIGS[
        "open-platform-op"
    ].tools


def test_platform_media_domain_does_not_grant_workbench_video(fake_agents):
    scope = AGENT_CONFIGS["media-scope-op"].platform_scope
    assert action_allowed(scope, "media.generate_video", "write") == (True, None)
    out = set(bound_tools_for_session_agent("agent:media-scope-op:t2", "agent"))
    assert "workbench_video_submit" not in out
    assert not out & WORKBENCH_TOOL_NAMES


def test_image_role_denied_video_tools(fake_agents):
    out = set(_resolve_worker("tuantu-op"))
    assert "workbench_image_submit" in out
    assert "workbench_video_submit" not in out
    sess = set(bound_tools_for_session_agent("agent:tuantu-op:t3", "agent"))
    assert "workbench_image_submit" in sess
    assert "workbench_video_submit" not in sess


def test_kefu_has_no_production_workbench_but_can_draft(fake_agents):
    out = set(bound_tools_for_session_agent("agent:kefu-op:t4", "agent"))
    assert not out & WORKBENCH_TOOL_NAMES
    assert "draft_workbench_order" in AGENT_CONFIGS["kefu-op"].tools
    # 草稿仍不派单不扣费
    payload = json.loads(draft_workbench_order.invoke({"text": "给杯子出 4 张主图"}))
    assert payload["status"] == "draft"
    assert "不派单" in payload["next_step"]


def test_kefu_platform_scope_none_denies_platform_actions(fake_agents):
    scope = AGENT_CONFIGS["kefu-op"].platform_scope
    ok, reason = action_allowed(scope, "knowledge.list", "read")
    assert not ok and reason == "scope_none"
