"""多 Bot 分岗 P0（1.4.13）：投放建议草稿工具行为回归。

- CRUD + submit_for_review 仅本地状态流转（draft → pending_review）；
- 提交后锁定（only_draft_editable）；查无返回 not_found；
- 工具模块零 HTTP 出站（无 requests/httpx/urllib import）；
- 验收 / 知识草稿：只 draft payload；knowledge summary 截断 ≤300。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(_BACKEND_ROOT / "packages" / "harness"))

from evoflow.collab import ad_suggestion_draft_store as store  # noqa: E402


@pytest.fixture()
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离本地草稿存储。

    ``config_dir()`` 对裸 EVOFLOW_HOME 不生效（只认 profiles 布局上溯），
    须用第一优先级的 ``EVOFLOW_CONFIG_DIR`` 指到临时目录，避免写进真实 ~/.evoflow。
    """
    home = tmp_path / "evoflow-home"
    home.mkdir()
    monkeypatch.setenv("EVOFLOW_HOME", str(home))
    monkeypatch.setenv("EVOFLOW_CONFIG_DIR", str(home))
    monkeypatch.setenv("EVOFLOW_UI_EXTENSIONS_DIR", str(home))
    yield home
    # store 模块无全局缓存；路径按 env 即时解析


def _create(action="budget", **kw):
    return store.create_draft(action=action, **kw)


class TestAdSuggestionDraftStore:
    def test_create_returns_draft_status(self, isolated_store):
        row = _create(target="计划A", suggested_value="300元/天", reason="ROI 拖底")
        assert row["status"] == "draft"
        assert row["action"] == "budget"
        assert row["draft_id"].startswith("ad-")

    def test_update_keeps_draft_and_changes_fields(self, isolated_store):
        row = _create(action="bid")
        updated = store.update_draft(row["draft_id"], suggested_value="1.8元")
        assert updated["status"] == "draft"
        assert updated["suggested_value"] == "1.8元"

    def test_get_list_roundtrip(self, isolated_store):
        a = _create(target="A")
        b = _create(target="B")
        assert store.get_draft(a["draft_id"])["target"] == "A"
        ids = {r["draft_id"] for r in store.list_drafts()}
        assert {a["draft_id"], b["draft_id"]} <= ids
        only_pending = store.list_drafts(status="pending_review")
        assert only_pending == []

    def test_submit_for_review_flips_status_no_http(self, isolated_store):
        row = _create()
        out = store.submit_for_review(row["draft_id"], note="人工复核一下")
        assert out["status"] == "pending_review"
        assert out["submitted_at"] is not None
        # 审计事件存在
        events = [e["event"] for e in out["events"]]
        assert "submitted_for_review" in events
        # 提交后锁定：不可再改
        locked = store.update_draft(row["draft_id"], suggested_value="9")
        assert locked is not None and "error" in locked

    def test_submit_nonexistent_returns_none(self, isolated_store):
        assert store.submit_for_review("ad-none") is None
        assert store.get_draft("") is None


class TestAdWatchToolsNoHttp:
    def test_tool_modules_have_no_http_imports(self):
        files = [
            _BACKEND_ROOT / "packages/harness/evoflow/tools/builtins/ad_watch_draft_tools.py",
            _BACKEND_ROOT / "packages/harness/evoflow/collab/ad_suggestion_draft_store.py",
            _BACKEND_ROOT / "packages/harness/evoflow/tools/builtins/ops_specialist_draft_tools.py",
        ]
        for f in files:
            src = f.read_text(encoding="utf-8")
            for bad in ("import requests", "import httpx", "import urllib", "aiohttp", "http.client"):
                assert bad not in src, f"{f.name} 不应含 HTTP 客户端（{bad}）"

    def test_tool_funcs_local_only(self, isolated_store):
        from evoflow.tools.builtins.ad_watch_draft_tools import (
            ad_anomaly_card_draft,
            ad_suggestion_draft_create,
            ad_suggestion_draft_get,
            ad_suggestion_draft_list,
            ad_suggestion_draft_update,
            ad_suggestion_submit_for_review,
            ad_watch_daily_draft,
        )

        daily = json.loads(ad_watch_daily_draft.func(summary="消耗平稳", metrics_snapshot=""))
        assert daily["status"] == "draft"
        assert daily["metrics_snapshot"] is None  # 占位字段允许空

        anomaly = json.loads(ad_anomaly_card_draft.func(anomaly_type="ctr_drop", product="A01"))
        assert anomaly["status"] == "draft"

        created = json.loads(
            ad_suggestion_draft_create.func(action="budget", target="计划A", suggested_value="300")
        )
        did = created["draft_id"]
        assert created["status"] == "draft"

        upd = json.loads(ad_suggestion_draft_update.func(draft_id=did, reason="成本顶格"))
        assert upd["reason"] == "成本顶格"

        got = json.loads(ad_suggestion_draft_get.func(draft_id=did))
        assert got["draft_id"] == did

        listed = json.loads(ad_suggestion_draft_list.func(status="draft"))
        assert listed["count"] >= 1

        submitted = json.loads(ad_suggestion_submit_for_review.func(draft_id=did, note="复核"))
        assert submitted["status"] == "pending_review"

        missing = json.loads(ad_suggestion_submit_for_review.func(draft_id="ad-nope"))
        assert missing["error"] == "not_found"


class TestSpecialistDraftTools:
    def test_ticket_and_knowledge_drafts_are_local_payloads(self, isolated_store):
        from evoflow.tools.builtins.ops_specialist_draft_tools import (
            team_knowledge_propose_draft,
            ticket_accept_note_draft,
            ticket_todo_draft,
        )

        note = json.loads(
            ticket_accept_note_draft.func(
                ticket_ref="WO-1", note="图片齐全", result="pass", todos="补一张细节图"
            )
        )
        assert note["status"] == "draft"
        assert note["result"] == "pass"

        todo = json.loads(ticket_todo_draft.func(ticket_ref="WO-1", items="1. 补图 2. 复验"))
        assert todo["status"] == "draft"

        long_summary = "长" * 500
        knowledge = json.loads(
            team_knowledge_propose_draft.func(title="选图经验", summary=long_summary)
        )
        assert knowledge["status"] == "draft"
        assert len(knowledge["summary"]) <= 300  # 截断 ≤300
        assert "admin" in knowledge["confirm_policy"]  # confirm 仅 admin
