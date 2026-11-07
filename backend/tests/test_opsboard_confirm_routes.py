"""opsboard 确认派单 / 跟单 / 验收路由：未确认零 HTTP；同号不双扣。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.gateway.routers import ops_summary as routes
from evoflow.collab.workbench_order_confirm import save_pending_draft
from evoflow.collab.workbench_order_draft import parse_one_liner_to_order_draft


@pytest.fixture()
def store_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "evoflow.collab.workbench_order_confirm.config_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(routes, "_conf", lambda: ("http://wb.test", "admin", "secret"))
    return tmp_path


def _seed(ref: str = "EV-ROUTE-1") -> dict:
    draft = parse_one_liner_to_order_draft("给这个杯子出 4 张主图，预算 20", external_ref=ref)
    return save_pending_draft(draft)


def test_upsert_draft_does_not_hit_workbench(store_root: Path, monkeypatch: pytest.MonkeyPatch):
    posts: list = []
    monkeypatch.setattr(routes, "_authed_post", lambda *a, **k: posts.append(a) or {})
    draft = parse_one_liner_to_order_draft("给这个杯子出 4 张主图", external_ref="EV-ROUTE-0")
    result = asyncio.run(routes.upsert_draft(routes.DraftBody(draft=draft)))
    assert result["ok"] is True
    assert result["draft"]["status"] == "draft"
    assert posts == []


def test_confirm_route_dispatches_once(store_root: Path, monkeypatch: pytest.MonkeyPatch):
    _seed("EV-ROUTE-1")
    posts: list = []

    def fake_post(path: str, payload: dict):
        posts.append((path, dict(payload)))
        return {"dispatched": True, "task_id": "t-9", "order": {"order_id": "o-9"}}

    monkeypatch.setattr(routes, "_authed_post", fake_post)
    first = asyncio.run(routes.confirm_draft("EV-ROUTE-1"))
    assert first["ok"] is True
    assert first["result"]["task_id"] == "t-9"
    assert len(posts) == 1
    assert posts[0][0] == "/api/opsboard/dispatch"
    assert posts[0][1]["external_ref"] == "EV-ROUTE-1"

    second = asyncio.run(routes.confirm_draft("EV-ROUTE-1"))
    assert second["result"]["deduped"] is True
    assert len(posts) == 1


def test_confirm_missing_404(store_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(routes, "_authed_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no http")))
    with pytest.raises(HTTPException) as err:
        asyncio.run(routes.confirm_draft("EV-MISSING"))
    assert err.value.status_code == 404


def test_orders_by_ref_filters(store_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        routes,
        "_authed_get",
        lambda path: {
            "orders": [
                {"order_id": "1", "external_ref": "EV-A"},
                {"order_id": "2", "external_ref": "EV-B"},
            ]
        },
    )
    out = asyncio.run(routes.orders_by_ref("EV-A"))
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["orders"][0]["order_id"] == "1"


def test_approve_reject_proxy(store_root: Path, monkeypatch: pytest.MonkeyPatch):
    posts: list = []

    def fake_post(path: str, payload: dict):
        posts.append((path, dict(payload)))
        return {"order_id": "oid", "review": {"status": "approved" if "approve" in path else "rejected"}}

    monkeypatch.setattr(routes, "_authed_post", fake_post)
    ok = asyncio.run(routes.approve_order("oid-1", routes.ReviewBody(note="好看")))
    bad = asyncio.run(routes.reject_order("oid-2", routes.ReviewBody(note="糊")))
    assert ok["ok"] and bad["ok"]
    assert posts[0][0].endswith("/approve")
    assert posts[1][0].endswith("/reject")
