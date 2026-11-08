"""多 Bot 分岗 P0（1.4.13）：岗位工具白名单 fail-closed 回归。

种子后走真实 ``resolve_worker_tool_allowlist``：
- 验收 / 知识 / 投放岗调 ``workbench_image_submit`` → 不可用；
- 投放工具只在 ad-watch-op 可用；submit 仍由 TOOL_RISK_LEVELS=confirm 闸住；
- 未种配置的专员（无 agent）不继承目录全集（fail-closed）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(_BACKEND_ROOT / "packages" / "harness"))

from evoflow.collab.ops_specialists import (  # noqa: E402
    AD_WATCH_OP,
    KNOWLEDGE_DEPOSIT_OP,
    OPS_BRAIN_ROUTER,
    TICKET_ACCEPT_OP,
    ensure_ops_specialist_agents,
)
from evoflow.collab.worker_tool_allowlist import resolve_worker_tool_allowlist  # noqa: E402
from evoflow.tools.builtins.workbench_tools import WORKBENCH_TOOL_NAMES  # noqa: E402

CATALOG = frozenset({
    "read", "bash", "replace", "write", "delete", "search_code_index",
    "view_image", "assets", "todo", "web_search", "fetch_url", "subagent",
    "tasks", "platform", "taskoutput", "taskstop",
    *WORKBENCH_TOOL_NAMES,
    "draft_workbench_order",
    "ad_watch_daily_draft", "ad_anomaly_card_draft",
    "ad_suggestion_draft_create", "ad_suggestion_draft_update",
    "ad_suggestion_draft_list", "ad_suggestion_draft_get",
    "ad_suggestion_submit_for_review",
    "ticket_accept_note_draft", "ticket_todo_draft",
    "team_knowledge_propose_draft",
    "knowledge_search", "knowledge_read",
})


def _write_minimal_config(home: Path) -> Path:
    cfg = home / "config.yaml"
    cfg.write_text(
        "models: []\ntools: []\nsandbox:\n  use: evoflow.sandbox.noop:NoopSandboxProvider\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def _resolve(assignee: str) -> set[str]:
    return set(
        resolve_worker_tool_allowlist(
            profile_tools=None,
            assignee_agent_code=assignee,
            base_subagent="general-purpose",
            subagent_config_tools=None,
            catalog_names=CATALOG,
        )
    )


class TestSpecialistAllowlistFailClosed:
    def test_no_specialist_gets_workbench_image_submit(self, isolated_db):
        ensure_ops_specialist_agents()
        for code in (OPS_BRAIN_ROUTER, TICKET_ACCEPT_OP, KNOWLEDGE_DEPOSIT_OP, AD_WATCH_OP):
            allowed = _resolve(code)
            assert "workbench_image_submit" not in allowed, f"{code} 越权拿到图片提交"
            assert "workbench_video_submit" not in allowed, f"{code} 越权拿到视频提交"

    def test_ad_tools_only_ad_watch_op(self, isolated_db):
        ensure_ops_specialist_agents()
        ad_names = {
            "ad_watch_daily_draft", "ad_anomaly_card_draft",
            "ad_suggestion_draft_create", "ad_suggestion_draft_update",
            "ad_suggestion_draft_list", "ad_suggestion_draft_get",
            "ad_suggestion_submit_for_review",
        }
        watch = _resolve(AD_WATCH_OP)
        assert ad_names <= watch
        for code in (OPS_BRAIN_ROUTER, TICKET_ACCEPT_OP, KNOWLEDGE_DEPOSIT_OP):
            allowed = _resolve(code)
            assert not (allowed & ad_names), f"{code} 越权拿到投放工具"

    def test_router_only_base_plus_draft(self, isolated_db):
        ensure_ops_specialist_agents()
        allowed = _resolve(OPS_BRAIN_ROUTER)
        # 含式 + 排除式（与 test_workbench_role_agents_seed 同风格；
        # resolver 会并入通用 worker 执行工具，属预期，不做全等断言）
        assert {"read", "bash"} <= allowed
        assert "draft_workbench_order" in allowed
        assert not any(t.startswith("workbench_") for t in allowed)
        assert not any(t.startswith("ad_") for t in allowed)

    def test_unknown_agent_fails_closed(self, isolated_db):
        # 未种配置的专员不继承目录全集：投放/工作台生产工具一律不可见
        allowed = _resolve("no-such-specialist")
        assert "ad_suggestion_submit_for_review" not in allowed
        assert "workbench_image_submit" not in allowed

    def test_submit_for_review_is_confirm_gated(self, isolated_db):
        from evoflow.agents.tool_approval_config import (
            RISK_CONFIRM,
            TOOL_RISK_LEVELS,
        )

        assert TOOL_RISK_LEVELS["ad_suggestion_submit_for_review"] == RISK_CONFIRM
        for t in (
            "ad_watch_daily_draft",
            "ad_anomaly_card_draft",
            "ad_suggestion_draft_create",
            "ad_suggestion_draft_update",
            "ad_suggestion_draft_list",
            "ad_suggestion_draft_get",
            "ticket_accept_note_draft",
            "ticket_todo_draft",
            "team_knowledge_propose_draft",
        ):
            assert TOOL_RISK_LEVELS[t] == "auto"
