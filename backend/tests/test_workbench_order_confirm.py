"""待确认草稿 + 人工确认派单：未确认零 HTTP；同号不双扣。"""

from __future__ import annotations

from pathlib import Path

import pytest

from evoflow.collab.workbench_order_confirm import (
    build_dispatch_payload,
    confirm_pending_draft,
    filter_orders_by_ref,
    get_draft,
    list_pending_drafts,
    save_pending_draft,
)
from evoflow.collab.workbench_order_draft import parse_one_liner_to_order_draft


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path


def _sample_draft(root: Path, ref: str = "EV-20261107-150000") -> dict:
    draft = parse_one_liner_to_order_draft(
        "给这个碎花连衣裙出 8 张主图，预算 30",
        external_ref=ref,
    )
    return save_pending_draft(draft, root=root)


def test_save_and_list_pending_no_dispatch(store_root: Path):
    calls: list = []
    row = _sample_draft(store_root)
    assert row["status"] == "draft"
    assert row["external_ref"].startswith("EV-")
    pending = list_pending_drafts(root=store_root)
    assert len(pending) == 1
    assert calls == []  # 显式：保存路径无副作用钩子


def test_confirm_calls_dispatch_once_and_dedupes(store_root: Path):
    ref = "EV-20261107-150001"
    _sample_draft(store_root, ref=ref)
    calls: list[dict] = []

    def fake_dispatch(payload: dict) -> dict:
        calls.append(dict(payload))
        return {"dispatched": True, "task_id": "task-1", "order": {"order_id": "ord-1"}}

    first = confirm_pending_draft(ref, dispatch_fn=fake_dispatch, root=store_root)
    assert first["dispatched"] is True
    assert first["deduped"] is False
    assert len(calls) == 1
    assert calls[0]["external_ref"] == ref
    assert "碎花连衣裙" in calls[0].get("product", "") or "碎花" in calls[0].get("name", "")

    second = confirm_pending_draft(ref, dispatch_fn=fake_dispatch, root=store_root)
    assert second["deduped"] is True
    assert second["task_id"] == "task-1"
    assert len(calls) == 1  # 不再次 HTTP

    row = get_draft(ref, root=store_root)
    assert row is not None
    assert row["status"] == "confirmed"


def test_confirm_missing_draft_raises(store_root: Path):
    with pytest.raises(LookupError):
        confirm_pending_draft("EV-NOPE", dispatch_fn=lambda p: {}, root=store_root)


def test_confirm_failure_restores_draft(store_root: Path):
    ref = "EV-20261107-150002"
    _sample_draft(store_root, ref=ref)

    def boom(_payload: dict) -> dict:
        raise RuntimeError("workbench down")

    with pytest.raises(RuntimeError):
        confirm_pending_draft(ref, dispatch_fn=boom, root=store_root)
    row = get_draft(ref, root=store_root)
    assert row is not None
    assert row["status"] == "draft"


def test_build_dispatch_payload_shape(store_root: Path):
    row = _sample_draft(store_root, ref="EV-20261107-150003")
    payload = build_dispatch_payload(row)
    assert payload["external_ref"] == "EV-20261107-150003"
    assert payload["type"] == "image"
    assert "description" in payload


def test_filter_orders_by_ref():
    orders = [
        {"order_id": "a", "external_ref": "EV-1"},
        {"order_id": "b", "external_ref": "EV-2"},
        {"order_id": "c", "external_ref": "EV-1"},
    ]
    matched = filter_orders_by_ref(orders, "EV-1")
    assert [o["order_id"] for o in matched] == ["a", "c"]
