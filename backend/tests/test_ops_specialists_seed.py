"""多 Bot 分岗 P0（1.4.13）：专员注册表 + 岗位种子回归。

- 种子写入后走真实 ``load_agent_config`` 断言五岗 tools ⊆ 白名单；
- Router 无 workbench_* 生产工具；投放工具只在 ad-watch-op；
- 工具源码与 import 图零投放平台生产写符号（qianchuan / oceanengine / ocean_engine）。

DB 隔离：独立临时 ``EVOFLOW_HOME`` + ``EVOFLOW_DB_PATH`` + 全量 schema
（与 ``test_workbench_role_agents_seed.py`` 同款夹具）。
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
    MAIN_IMAGE_OP,
    OPS_BRAIN_ROUTER,
    STRIPE_SPECIALIST_CODES,
    TICKET_ACCEPT_OP,
    ensure_ops_specialist_agents,
    get_ops_specialist,
    list_ops_specialists,
)
from evoflow.tools.builtins.workbench_tools import WORKBENCH_TOOL_NAMES  # noqa: E402

FORBIDDEN_SYMBOLS = ("qianchuan", "oceanengine", "ocean_engine")


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


class TestOpsSpecialistRegistry:
    def test_five_p0_specialists_registered(self):
        codes = [s.code for s in list_ops_specialists()]
        assert codes == [
            OPS_BRAIN_ROUTER,
            MAIN_IMAGE_OP,
            TICKET_ACCEPT_OP,
            KNOWLEDGE_DEPOSIT_OP,
            AD_WATCH_OP,
        ]
        assert OPS_BRAIN_ROUTER not in STRIPE_SPECIALIST_CODES
        assert len(STRIPE_SPECIALIST_CODES) == 4

    def test_get_ops_specialist(self):
        assert get_ops_specialist("ad-watch-op") is not None
        assert get_ops_specialist("no-such-op") is None


class TestOpsSpecialistSeed:
    def test_seed_idempotent_and_tools_within_whitelist(self, isolated_db):
        from evoflow.config.agents_config import load_agent_config

        out1 = ensure_ops_specialist_agents()
        out2 = ensure_ops_specialist_agents()  # 幂等
        assert set(out1) == set(out2)

        for code, seeded_tools in out1.items():
            spec = get_ops_specialist(code)
            assert spec is not None
            cfg = load_agent_config(code)
            assert cfg is not None
            assert list(cfg.tools) == seeded_tools
            # 种子 tools ⊆ 注册表白名单（fail-closed：不得越权多挂）
            assert set(seeded_tools) <= set(spec.tools)
            assert cfg.agent_name == spec.name

    def test_router_has_no_workbench_or_ad_tools(self, isolated_db):
        ensure_ops_specialist_agents()
        from evoflow.config.agents_config import load_agent_config

        cfg = load_agent_config(OPS_BRAIN_ROUTER)
        tools = set(cfg.tools or [])
        # Router：只有基础工具 + 工单草稿；无 workbench 生产、无 ad_*
        assert "draft_workbench_order" in tools
        assert not (tools & set(WORKBENCH_TOOL_NAMES))
        assert not any(t.startswith("ad_") for t in tools)

    def test_main_image_op_shares_tuantu_toolset(self, isolated_db):
        from evoflow.collab.workbench_role_agents import ensure_workbench_role_agents

        ensure_workbench_role_agents()
        ensure_ops_specialist_agents()
        from evoflow.config.agents_config import load_agent_config

        tuantu = set(load_agent_config("tuantu-op").tools or [])
        main_image = set(load_agent_config(MAIN_IMAGE_OP).tools or [])
        # 别名岗与生产岗同一工具集（不改 tuantu-op 种子语义）
        assert main_image == tuantu
        assert "workbench_image_submit" in main_image

    def test_ad_tools_only_on_ad_watch_op(self, isolated_db):
        out = ensure_ops_specialist_agents()
        ad_tools = {
            "ad_watch_daily_draft",
            "ad_anomaly_card_draft",
            "ad_suggestion_draft_create",
            "ad_suggestion_draft_update",
            "ad_suggestion_draft_list",
            "ad_suggestion_draft_get",
            "ad_suggestion_submit_for_review",
        }
        for code, tools in out.items():
            overlap = set(tools) & ad_tools
            if code == AD_WATCH_OP:
                assert overlap == ad_tools
            else:
                assert overlap == set(), f"{code} 不应挂投放工具: {overlap}"

    def test_ticket_knowledge_only_draft_tools(self, isolated_db):
        out = ensure_ops_specialist_agents()
        ticket = set(out[TICKET_ACCEPT_OP])
        knowledge = set(out[KNOWLEDGE_DEPOSIT_OP])
        assert {"ticket_accept_note_draft", "ticket_todo_draft"} <= ticket
        assert "team_knowledge_propose_draft" in knowledge
        # 无 workbench 生产 / 无 ad_*；无自动 accept
        for tools in (ticket, knowledge):
            assert not (tools & set(WORKBENCH_TOOL_NAMES))
            assert not any(t.startswith("ad_") for t in tools)


class TestNoProductionAdSymbols:
    def test_source_zero_forbidden_symbols(self):
        files = [
            _BACKEND_ROOT
            / "packages/harness/evoflow/collab/ops_specialists.py",
            _BACKEND_ROOT
            / "packages/harness/evoflow/collab/ad_suggestion_draft_store.py",
            _BACKEND_ROOT
            / "packages/harness/evoflow/tools/builtins/ad_watch_draft_tools.py",
            _BACKEND_ROOT
            / "packages/harness/evoflow/tools/builtins/ops_specialist_draft_tools.py",
        ]
        for f in files:
            src = f.read_text(encoding="utf-8").lower()
            for sym in FORBIDDEN_SYMBOLS:
                assert sym not in src, f"{f.name} 含禁区符号 {sym}"

    def test_store_status_enum_has_no_production(self):
        from evoflow.collab.ad_suggestion_draft_store import AD_DRAFT_STATUSES

        assert AD_DRAFT_STATUSES == frozenset({"draft", "pending_review", "discarded"})
        for status in AD_DRAFT_STATUSES:
            assert "production" not in status
            assert "applied" not in status
