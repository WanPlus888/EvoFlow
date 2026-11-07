"""套图岗 / 视频岗员工配置种子回归（阶段1收口）。

这组测例测「种子写入后的真 load」——走真实 ``load_agent_config`` /
``resolve_worker_tool_allowlist`` / ``bound_tools_for_session_agent``，
不 monkeypatch 成假字典（旧 ``test_workbench_role_allowlist.py`` 的假夹具保留不动）。

DB 隔离：每个测试独立临时 ``EVOFLOW_HOME`` + ``EVOFLOW_DB_PATH``，
并建全量 schema（``ensure_app_schema``），绝不触碰用户真实 EVOFLOW_HOME DB。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(_BACKEND_ROOT / "packages" / "harness"))

from evoflow.collab.workbench_role_agents import (  # noqa: E402
    BASE_TOOLS,
    DRAFT_WORKBENCH_ORDER_TOOL,
    IMAGE_WORKBENCH_TOOLS,
    KEFU_OP,
    ROLE_PLATFORM_SCOPES,
    SHIPIN_OP,
    TUANTU_OP,
    VIDEO_WORKBENCH_TOOLS,
    ensure_workbench_role_agents,
)
from evoflow.collab.worker_tool_allowlist import resolve_worker_tool_allowlist  # noqa: E402
from evoflow.config.agents_config import load_agent_config, save_agent_config  # noqa: E402
from evoflow.session_tool_binding.agent_tools import bound_tools_for_session_agent  # noqa: E402
from evoflow.tools.builtins.workbench_tools import WORKBENCH_TOOL_NAMES  # noqa: E402

IMAGE_TOOLS = set(IMAGE_WORKBENCH_TOOLS)
VIDEO_TOOLS = set(VIDEO_WORKBENCH_TOOLS)

# 模拟运行时工具目录（get_available_tools 的名字面），含全部工作台工具。
# resolve_worker_tool_allowlist 的 catalog_names 由调用方提供，这里给全集，
# 以便观察种子写入的真实 AgentConfig.tools 是否会被正确解析。
CATALOG = frozenset({
    "read", "bash", "replace", "write", "delete", "search_code_index",
    "view_image", "assets", "todo", "web_search", "fetch_url", "subagent",
    "tasks", "platform", "panel_set", "read_lints", "taskoutput", "taskstop",
    *WORKBENCH_TOOL_NAMES,
})


def _write_minimal_config(home: Path) -> Path:
    """写一份最小 config.yaml，避免 AppConfig.from_file 在测试里炸。"""
    cfg = home / "config.yaml"
    cfg.write_text(
        "models: []\ntools: []\nsandbox:\n  use: evoflow.sandbox.noop:NoopSandboxProvider\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """每个测试独立 EVOFLOW_HOME + EVOFLOW_DB_PATH，全量 schema。"""
    from evoflow.persistence import db as db_mod
    from evoflow.persistence.schema import ensure_app_schema

    home = tmp_path / "evoflow-home"
    home.mkdir()
    cfg_path = _write_minimal_config(home)
    monkeypatch.setenv("EVOFLOW_HOME", str(home))
    monkeypatch.setenv("EVOFLOW_DB_PATH", str(home / "evoflow.db"))
    monkeypatch.setenv("EVOFLOW_CONFIG_PATH", str(cfg_path))
    db_mod.reset_db_for_tests()
    conn = db_mod.get_db()
    ensure_app_schema(conn)
    yield home
    db_mod.reset_db_for_tests()


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


# ── 1) 种子写入后的真 load ─────────────────────────────────────────────


def test_ensure_seeds_tuantu_and_shipin_tools(isolated_db):
    result = ensure_workbench_role_agents()

    assert set(result) == {TUANTU_OP, SHIPIN_OP, KEFU_OP}
    assert result[TUANTU_OP] == [*BASE_TOOLS, *IMAGE_WORKBENCH_TOOLS]
    assert result[SHIPIN_OP] == [*BASE_TOOLS, *VIDEO_WORKBENCH_TOOLS]
    assert result[KEFU_OP] == list(BASE_TOOLS)

    tuantu = load_agent_config(TUANTU_OP)
    assert tuantu.agent_name == "套图岗"
    assert tuantu.tools is not None
    assert IMAGE_TOOLS <= set(tuantu.tools)
    assert "workbench_video_submit" not in tuantu.tools

    shipin = load_agent_config(SHIPIN_OP)
    assert shipin.agent_name == "视频岗"
    assert shipin.tools is not None
    assert VIDEO_TOOLS <= set(shipin.tools)
    assert "workbench_image_submit" not in shipin.tools

    kefu = load_agent_config(KEFU_OP)
    assert kefu.agent_name == "客服岗"
    assert kefu.tools is not None
    assert not any(t.startswith("workbench_") for t in kefu.tools)
    # 草稿三岗可见；不在生产 WORKBENCH 集合
    assert DRAFT_WORKBENCH_ORDER_TOOL in tuantu.tools
    assert DRAFT_WORKBENCH_ORDER_TOOL in shipin.tools
    assert DRAFT_WORKBENCH_ORDER_TOOL in kefu.tools
    assert DRAFT_WORKBENCH_ORDER_TOOL not in WORKBENCH_TOOL_NAMES
    # L1 platform_scope 种子
    assert tuantu.platform_scope is not None
    assert tuantu.platform_scope.mode == ROLE_PLATFORM_SCOPES[TUANTU_OP]["mode"]
    assert tuantu.platform_scope.domains == ROLE_PLATFORM_SCOPES[TUANTU_OP]["domains"]
    assert shipin.platform_scope is not None
    assert shipin.platform_scope.mode == "custom"
    assert kefu.platform_scope is not None
    assert kefu.platform_scope.mode == "none"


# ── 2) 幂等 ────────────────────────────────────────────────────────────


def test_ensure_is_idempotent(isolated_db):
    first = ensure_workbench_role_agents()
    second = ensure_workbench_role_agents()
    assert first == second

    for code in (TUANTU_OP, SHIPIN_OP, KEFU_OP):
        assert load_agent_config(code).tools == first[code]


def test_ensure_preserves_unrelated_agent_and_fields(isolated_db):
    save_agent_config("keep-me", {
        "agent_code": "keep-me",
        "agent_name": "无关员工",
        "agent_type": "custom",
        "tools": ["read", "bash"],
        "description": "不应被种子碰到",
        "model": "probe-model",
    })
    save_agent_config(TUANTU_OP, {
        "agent_code": TUANTU_OP,
        "agent_name": "旧名字",
        "agent_type": "custom",
        "tools": ["read"],
        "description": "自定义描述应保留",
    })

    ensure_workbench_role_agents()

    keep = load_agent_config("keep-me")
    assert keep.agent_name == "无关员工"
    assert keep.tools == ["read", "bash"]
    assert keep.description == "不应被种子碰到"
    assert keep.model == "probe-model"

    tuantu = load_agent_config(TUANTU_OP)
    assert tuantu.description == "自定义描述应保留"  # 其它字段保持
    assert tuantu.agent_name == "套图岗"  # 岗位名覆盖
    assert IMAGE_TOOLS <= set(tuantu.tools)


# ── 3) worker 路径（task_tool 派活）────────────────────────────────────


def test_seeded_tuantu_worker_allowlist_excludes_video_submit(isolated_db):
    ensure_workbench_role_agents()
    out = set(_resolve_worker(TUANTU_OP))
    assert "workbench_image_submit" in out
    assert "workbench_video_submit" not in out
    assert IMAGE_TOOLS <= out
    assert {"read", "bash"} <= out


def test_seeded_shipin_worker_allowlist_excludes_image_submit(isolated_db):
    ensure_workbench_role_agents()
    out = set(_resolve_worker(SHIPIN_OP))
    assert "workbench_video_submit" in out
    assert "workbench_image_submit" not in out
    assert VIDEO_TOOLS <= out


# ── 4) 会话路径（员工值守/聊天会话绑定）──────────────────────────────────


def test_seeded_shipin_session_binding_excludes_image_submit(isolated_db):
    ensure_workbench_role_agents()
    out = set(bound_tools_for_session_agent("agent:shipin-op:seed-test", "agent"))
    assert "workbench_video_submit" in out
    assert "workbench_image_submit" not in out
    assert VIDEO_TOOLS <= out
    assert {"read", "bash"} <= out


def test_seeded_tuantu_session_binding_excludes_video_submit(isolated_db):
    ensure_workbench_role_agents()
    out = set(bound_tools_for_session_agent("agent:tuantu-op:seed-test", "agent"))
    assert "workbench_image_submit" in out
    assert "workbench_video_submit" not in out
    assert IMAGE_TOOLS <= out


def test_seeded_kefu_session_binding_gets_no_workbench(isolated_db):
    ensure_workbench_role_agents()
    out = set(bound_tools_for_session_agent("agent:kefu-op:seed-test", "agent"))
    assert not out & WORKBENCH_TOOL_NAMES
    assert {"read", "bash"} <= out


# ── 5) 改能力后下一轮生效（invalidate 去重路径）──────────────────────────


def test_seeded_capability_change_next_turn_after_invalidate(isolated_db):
    """改 tools / platform_scope 后 invalidate，会话绑定立刻反映（下一轮生效）。"""
    from evoflow.config.agents_config import invalidate_agent_config_cache, save_agent_config

    ensure_workbench_role_agents()
    before = set(bound_tools_for_session_agent("agent:tuantu-op:cap-refresh", "agent"))
    assert "workbench_image_submit" in before
    assert "workbench_video_submit" not in before

    cfg = load_agent_config(TUANTU_OP)
    payload = cfg.model_dump(mode="python", exclude={"name"})
    # 收窄为仅 products_list（去掉 image_submit）
    payload["tools"] = [t for t in (cfg.tools or []) if t != "workbench_image_submit"]
    payload["platform_scope"] = {"mode": "none", "domains": [], "actions": [], "max_risk": "write"}
    save_agent_config(TUANTU_OP, payload)
    invalidate_agent_config_cache(TUANTU_OP)

    after = set(bound_tools_for_session_agent("agent:tuantu-op:cap-refresh", "agent"))
    assert "workbench_image_submit" not in after
    assert "workbench_products_list" in after
    reloaded = load_agent_config(TUANTU_OP)
    assert reloaded.platform_scope is not None
    assert reloaded.platform_scope.mode == "none"
