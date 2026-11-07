"""P1：节点级工作流能力（官方 1.3.4）× 工作台 fail-closed。

钉死：
- 节点可显式挂非工作台 tools / skills / mcp / knowledge / model / thinking
- 节点挂 workbench_* 不得冲开执行者岗位白名单（套图拿不到视频；客服拿不到生产工具）
- 授权岗节点挂自己的 workbench 子集仍可用
- 应用 project_path 列启动补齐仍在（schema 回归）
"""

from __future__ import annotations

import pytest

from evoflow.collab.app_schema import normalize_app_document
from evoflow.collab.plan_subtasks_sync import build_worker_profile_from_step
from evoflow.collab.worker_tool_allowlist import resolve_worker_tool_allowlist
from evoflow.config.agents_config import AgentConfig
from evoflow.session_tool_binding import agent_tools as agent_tools_mod
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

CATALOG = frozenset(
    {
        "read",
        "bash",
        "todo",
                "web_search",
        "draft_workbench_order",
        *WORKBENCH_TOOL_NAMES,
    }
)

AGENT_CONFIGS: dict[str, AgentConfig] = {
    "tuantu-op": AgentConfig(
        agent_code="tuantu-op",
        agent_name="套图岗",
        tools=["read", "bash", "todo", *sorted(IMAGE_WORKBENCH_TOOLS)],
    ),
    "shipin-op": AgentConfig(
        agent_code="shipin-op",
        agent_name="视频岗",
        tools=["read", "bash", "todo", *sorted(VIDEO_WORKBENCH_TOOLS)],
    ),
    "kefu-op": AgentConfig(
        agent_code="kefu-op",
        agent_name="客服岗",
        tools=["read", "bash", "todo", "draft_workbench_order"],
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
        lambda session_key: _universe_for("main"),
    )
    monkeypatch.setattr(
        "evoflow.persistence.db.get_db",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db in unit tests")),
    )
    return AGENT_CONFIGS


def _resolve(assignee: str | None, profile_tools: list[str] | None) -> list[str]:
    return resolve_worker_tool_allowlist(
        profile_tools=profile_tools,
        assignee_agent_code=assignee,
        base_subagent="general-purpose",
        subagent_config_tools=None,
        catalog_names=set(CATALOG),
        session_key=None,
        session_mode="agent",
    )


def test_node_tools_non_workbench_pass_through(fake_agents):
    """节点级挂 read/view_image 等非工作台工具按声明生效。"""
    out = set(_resolve("tuantu-op", ["read", "todo"]))
    assert {"read", "todo"} <= out
    assert not (out & (WORKBENCH_TOOL_NAMES - IMAGE_WORKBENCH_TOOLS))


def test_image_node_cannot_mount_video_workbench(fake_agents):
    """套图岗节点声明 video_submit → 剥离。"""
    out = set(
        _resolve(
            "tuantu-op",
            ["read", "workbench_image_submit", "workbench_video_submit"],
        )
    )
    assert "workbench_image_submit" in out
    assert "workbench_video_submit" not in out
    assert "read" in out


def test_kefu_node_cannot_mount_any_production_workbench(fake_agents):
    out = set(
        _resolve(
            "kefu-op",
            ["read", "workbench_image_submit", "workbench_video_submit"],
        )
    )
    assert "read" in out
    assert not out & WORKBENCH_TOOL_NAMES


def test_video_node_keeps_own_workbench_subset(fake_agents):
    out = set(
        _resolve(
            "shipin-op",
            ["read", "workbench_video_submit", "workbench_video_status"],
        )
    )
    assert {"read", "workbench_video_submit", "workbench_video_status"} <= out
    assert "workbench_image_submit" not in out


def test_step_worker_profile_carries_node_capabilities():
    """plan_subtasks_sync 把节点 skills/tools/mcp/knowledge/model/thinking 写入 worker_profile。"""
    step = {
        "ref": "1",
        "name": "套图提交",
        "goal": "出主图",
        "assigned_agent": "tuantu-op",
        "instruction": "按商品档案出 4 张主图",
        "tools": ["read", "workbench_image_submit", "workbench_image_status"],
        "skills": ["summarize"],
        "mcp_servers": [],
        "knowledge_vault_ids": ["ops-kb"],
        "model": "glm-4.6",
        "thinking_enabled": True,
        "project_path": "/tmp/ops-ws",
    }
    wp = build_worker_profile_from_step(step, assigned="tuantu-op", depends_refs=[])
    assert wp["base_subagent"] == "tuantu-op"
    assert "workbench_image_submit" in (wp.get("tools") or [])
    assert wp.get("skills") == ["summarize"]
    assert wp.get("knowledge_vault_ids") == ["ops-kb"]
    assert wp.get("model") == "glm-4.6"
    assert wp.get("thinking_enabled") is True


def test_normalize_app_keeps_project_path_and_node_caps():
    doc = normalize_app_document(
        {
            "name": "套图到质检",
            "project_path": "/data/ops/image-qa",
            "plan": {
                "goal": "套图后质检",
                "project_path": "/data/ops/image-qa",
                "steps": [
                    {
                        "ref": "1",
                        "name": "套图",
                        "assigned_agent": "tuantu-op",
                        "tools": ["workbench_image_submit"],
                        "skills": ["summarize"],
                        "thinking_enabled": False,
                        "depends_on": [],
                    },
                    {
                        "ref": "2",
                        "name": "质检",
                        "assigned_agent": "kefu-op",
                        "tools": ["read", "view_image"],
                        "depends_on": ["1"],
                    },
                ],
            },
        }
    )
    assert doc.get("project_path") == "/data/ops/image-qa"
    steps = doc["plan"]["steps"]
    assert steps[0]["tools"] == ["workbench_image_submit"] or "workbench_image_submit" in str(
        steps[0].get("tools")
    )
    assert steps[0].get("thinking_enabled") is False


def test_project_path_post_baseline_column_listed():
    """启动迁移清单仍含 evoflow_apps.project_path（旧库覆盖安装可补列）。"""
    import inspect

    from evoflow.persistence import schema as schema_mod

    legacy = schema_mod._LEGACY_COLUMN_BACKFILL.get("evoflow_apps", ())
    assert any(col == "project_path" for col, _def in legacy)
    body = inspect.getsource(schema_mod._ensure_post_baseline_columns)
    assert "project_path" in body
    assert "evoflow_apps" in body
