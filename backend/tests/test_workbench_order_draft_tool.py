"""draft_workbench_order 工具测试：只出草稿，不派单、不扣费。"""

from __future__ import annotations

import json

from evoflow.tools.builtins.workbench_order_draft_tool import draft_workbench_order


def _invoke(text: str, external_ref: str = "") -> dict:
    raw = draft_workbench_order.invoke({"text": text, "external_ref": external_ref})
    return json.loads(raw)


def test_tool_returns_json_draft_not_dispatch():
    payload = _invoke("给这个碎花连衣裙出 8 张主图，预算 30")

    assert payload["status"] == "draft"
    assert payload["type"] == "image"
    assert "8" in str(payload["qty"])
    assert "30" in str(payload["budget"])
    # 绝不声称派单成功，且 next_step 明确说明不派单
    assert "dispatch" not in json.dumps(payload, ensure_ascii=False)
    assert "不派单" in payload["next_step"]
    # 工具输出里不能出现对派单接口的成功声称
    assert "/api/opsboard/dispatch" not in payload["next_step"]


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


def test_needs_confirm_path():
    payload = _invoke("按卖点拍 15 秒口播")

    assert payload["needs_confirm"] is True
    assert payload["needs_confirm_fields"]
    assert "确认" in payload["next_step"]
