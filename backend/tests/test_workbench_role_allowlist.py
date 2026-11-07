"""工作台工具按岗白名单：套图岗 / 视频岗 / 未授权角色。

仓库内没有套图/视频预设员工，按派活要求用最小本地夹具：
- ``tuantu-op``（套图岗）：products_list + image_submit + image_status
- ``shipin-op``（视频岗）：products_list + video_options + video_submit + video_status
- ``kefu-op``（未授权角色，有 tools 配置但不含工作台工具）
- ``nobody-op``（无 AgentConfig，模拟「继承全量」的旧漏洞）

验收点：
- 套图岗调视频提交被拒；视频岗调套图提交被拒（解析出的白名单里没有对方工具）。
- 未授权/无配置角色调任何 workbench submit 被拒（worker 继承与会话绑定双路径）。
- 授权岗可以解析到自己那组工具名。
"""

from __future__ import annotations

import pytest

from evoflow.collab.worker_tool_allowlist import resolve_worker_tool_allowlist
from evoflow.config.agents_config import AgentConfig
from evoflow.session_tool_binding import agent_tools as agent_tools_mod
from evoflow.session_tool_binding.agent_tools import bound_tools_for_session_agent
from evoflow.tools.builtins.workbench_tools import WORKBENCH_TOOL_NAMES

IMAGE_WORKBENCH_TOOLS = {
    "workbench_products_list",
    "workbench_image_submit",
    "workbench_image_status",
}
VIDEO_WORKBENCH_TOOLS = {
    "workbench_products_list",
    "workbench_video_options",
    "workbench_video_submit",
    "workbench_video_status",
}

# 模拟运行时工具目录（get_available_tools 的名字面），含全部工作台工具
CATALOG = frozenset({
    "read", "bash", "replace", "write", "delete", "search_code_index",
    "view_image", "assets", "todo", "web_search", "fetch_url", "subagent",
    "tasks", "platform", "panel_set", "read_lints", "taskoutput", "taskstop",
    *WORKBENCH_TOOL_NAMES,
})

AGENT_CONFIGS: dict[str, AgentConfig] = {
    "tuantu-op": AgentConfig(
        agent_code="tuantu-op",
        agent_name="套图岗",
        tools=["read", "bash", "todo", "view_image", *sorted(IMAGE_WORKBENCH_TOOLS)],
    ),
    "shipin-op": AgentConfig(
        agent_code="shipin-op",
        agent_name="视频岗",
        tools=["read", "bash", "todo", "view_image", *sorted(VIDEO_WORKBENCH_TOOLS)],
    ),
    "kefu-op": AgentConfig(
        agent_code="kefu-op",
        agent_name="客服岗",
        tools=["read", "bash", "todo"],
    ),
}


def _fake_load_agent_config(name):
    cfg = AGENT_CONFIGS.get(str(name or "").strip().lower())
    if cfg is None:
        raise FileNotFoundError(f"Agent config not found in database: {name!r}")
    return cfg


def _universe_for(agent_id: str) -> frozenset[str]:
    """镜像真实语义：无配置 / tools=None → 全量 universe（旧的「大礼包」路径）。"""
    cfg = AGENT_CONFIGS.get(str(agent_id or "").strip().lower())
    if cfg is None or cfg.tools is None:
        return CATALOG
    return frozenset(t.strip().lower() for t in cfg.tools if str(t or "").strip())


@pytest.fixture()
def fake_agent_configs(monkeypatch: pytest.MonkeyPatch):
    """替换 AgentConfig 读取，隔离真实 SQLite；worker 继承路径同样走夹具。"""
    monkeypatch.setattr("evoflow.config.agents_config.load_agent_config", _fake_load_agent_config)
    # agent_tools.py 在模块导入时绑定了 load_agent_config，需要一并替换
    monkeypatch.setattr(agent_tools_mod, "load_agent_config", _fake_load_agent_config)
    # 隔离真实 get_available_tools（继承回退用），并避免测试触碰真实 DB
    monkeypatch.setattr(
        agent_tools_mod, "resolve_agent_tool_names_for_agent",
        lambda agent_id, **_k: _universe_for(agent_id),
    )
    monkeypatch.setattr(
        agent_tools_mod, "resolve_agent_tool_names_for_session",
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


def _resolve_worker(assignee: str | None, *, profile_tools: list[str] | None = None) -> list[str]:
    return resolve_worker_tool_allowlist(
        profile_tools=profile_tools,
        assignee_agent_code=assignee,
        base_subagent="general-purpose",
        subagent_config_tools=None,
        catalog_names=set(CATALOG),
        session_key=None,
        session_mode="agent",
    )


# ── worker 路径（task_tool 派活）──────────────────────────────────


def test_image_role_resolves_only_image_workbench_tools(fake_agent_configs):
    out = set(_resolve_worker("tuantu-op"))
    assert IMAGE_WORKBENCH_TOOLS <= out                      # 授权岗解析到自己那组工具
    assert not out & (WORKBENCH_TOOL_NAMES - IMAGE_WORKBENCH_TOOLS)  # 套图岗调视频提交被拒
    assert {"read", "bash"} <= out                           # 普通工作工具不受影响


def test_video_role_resolves_only_video_workbench_tools(fake_agent_configs):
    out = set(_resolve_worker("shipin-op"))
    assert VIDEO_WORKBENCH_TOOLS <= out
    assert not out & (WORKBENCH_TOOL_NAMES - VIDEO_WORKBENCH_TOOLS)  # 视频岗调套图提交被拒
    assert {"read", "bash"} <= out


def test_unauthorized_role_worker_gets_no_workbench_tools(fake_agent_configs):
    out = set(_resolve_worker("kefu-op"))
    assert not out & WORKBENCH_TOOL_NAMES                    # 未授权角色调任何 workbench submit 被拒
    assert {"read", "bash"} <= out


def test_unconfigured_agent_inherits_no_workbench_tools(fake_agent_configs):
    """无 AgentConfig 的角色走继承回退，也不允许拿到工作台工具（默认拒绝）。"""
    out = set(_resolve_worker(None))
    assert not out & WORKBENCH_TOOL_NAMES
    assert {"read", "bash"} <= out                           # 继承的非工作台工具仍在


def test_worker_profile_explicit_grant_still_works(fake_agent_configs):
    """显式 worker_profile.tools 是授权面：套图 worker 仍可拿 image_submit。"""
    out = set(_resolve_worker(None, profile_tools=["read", "workbench_image_submit"]))
    assert {"read", "workbench_image_submit"} <= out
    assert "workbench_video_submit" not in out


# ── 会话路径（员工值守/聊天会话绑定）──────────────────────────────


def test_session_binding_image_role_gets_only_image_tools(fake_agent_configs):
    out = set(bound_tools_for_session_agent("agent:tuantu-op:t1", "agent"))
    assert IMAGE_WORKBENCH_TOOLS <= out
    assert not out & (WORKBENCH_TOOL_NAMES - IMAGE_WORKBENCH_TOOLS)
    assert {"read", "bash"} <= out


def test_session_binding_video_role_gets_only_video_tools(fake_agent_configs):
    out = set(bound_tools_for_session_agent("agent:shipin-op:t2", "agent"))
    assert VIDEO_WORKBENCH_TOOLS <= out
    assert not out & (WORKBENCH_TOOL_NAMES - VIDEO_WORKBENCH_TOOLS)


def test_session_binding_unauthorized_role_gets_no_workbench(fake_agent_configs):
    out = set(bound_tools_for_session_agent("agent:kefu-op:t3", "agent"))
    assert not out & WORKBENCH_TOOL_NAMES
    assert {"read", "bash"} <= out


def test_session_binding_unconfigured_agent_gets_no_workbench(fake_agent_configs):
    """旧的「大礼包」路径：无配置 agent universe=全量，也必须被门禁拦下。"""
    out = set(bound_tools_for_session_agent("agent:nobody-op:t4", "agent"))
    assert not out & WORKBENCH_TOOL_NAMES
    assert {"read", "bash"} <= out


def test_session_binding_tool_search_enabled_still_gates(fake_agent_configs, monkeypatch):
    """tool_search 开启时走 bound-only 模式目录，门禁同样生效。"""
    monkeypatch.setattr(agent_tools_mod, "_tool_search_enabled", lambda: True)
    out = set(bound_tools_for_session_agent("agent:nobody-op:t5", "agent"))
    assert not out & WORKBENCH_TOOL_NAMES
    out_role = set(bound_tools_for_session_agent("agent:tuantu-op:t6", "agent"))
    assert IMAGE_WORKBENCH_TOOLS <= out_role


def test_session_binding_proactive_duty_session_gated_by_agent(fake_agent_configs):
    """员工值守会话（proactive:{agent_code}）按其岗位 agent 门禁。"""
    out = set(bound_tools_for_session_agent("proactive:shipin-op", "agent"))
    assert VIDEO_WORKBENCH_TOOLS <= out
    assert "workbench_image_submit" not in out
