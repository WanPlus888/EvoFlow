"""draft_workbench_order 工具测试：只出草稿，不派单、不扣费。"""

from __future__ import annotations

import json
from pathlib import Path

from evoflow.tools.builtins.workbench_order_draft_tool import draft_workbench_order


def _invoke(text: str, external_ref: str = "") -> dict:
    raw = draft_workbench_order.invoke({"text": text, "external_ref": external_ref})
    return json.loads(raw)


def test_tool_returns_json_draft_not_dispatch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "evoflow.collab.workbench_order_confirm.config_dir",
        lambda: tmp_path,
    )
    posts: list = []
    monkeypatch.setattr(
        "app.gateway.routers.ops_summary._authed_post",
        lambda *a, **k: posts.append(a) or {},
        raising=False,
    )
    payload = _invoke("给这个碎花连衣裙出 8 张主图，预算 30")

    assert payload["status"] == "draft"
    assert payload["type"] == "image"
    assert "8" in str(payload["qty"])
    assert "30" in str(payload["budget"])
    assert "dispatch" not in json.dumps(payload, ensure_ascii=False).lower() or "不派单" in payload["next_step"]
    assert "不派单" in payload["next_step"]
    assert "/api/opsboard/dispatch" not in payload["next_step"]
    assert posts == []


def test_tool_persists_local_draft_without_http(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "evoflow.collab.workbench_order_confirm.config_dir",
        lambda: tmp_path,
    )
    payload = _invoke("给这个杯子出 4 张主图，预算 15", external_ref="EV-TOOL-1")
    from evoflow.collab.workbench_order_confirm import get_draft

    row = get_draft("EV-TOOL-1", root=tmp_path)
    assert row is not None
    assert row["status"] == "draft"
    assert payload["external_ref"] == "EV-TOOL-1"


def test_tool_name_not_in_workbench_tool_names():
    from evoflow.tools.builtins.workbench_tools import WORKBENCH_TOOL_NAMES

    assert "draft_workbench_order" not in WORKBENCH_TOOL_NAMES


def test_builtin_catalog_includes_draft_tool():
    from evoflow.tools.tools import get_builtin_tools

    get_builtin_tools.cache_clear()
    try:
        names = [getattr(t, "name", None) for t in get_builtin_tools()]
    finally:
        get_builtin_tools.cache_clear()
    assert "draft_workbench_order" in names


def test_needs_confirm_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "evoflow.collab.workbench_order_confirm.config_dir",
        lambda: tmp_path,
    )
    payload = _invoke("按卖点拍 15 秒口播")

    assert payload["needs_confirm"] is True
    assert payload["needs_confirm_fields"]
    assert "确认" in payload["next_step"]
