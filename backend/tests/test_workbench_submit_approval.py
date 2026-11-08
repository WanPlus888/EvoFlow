"""工作台 submit 强制确认闸回归（运营大脑 1.4.12 能力扩展 · 口径C）。

- ``workbench_image_submit`` / ``workbench_video_submit`` → RISK_CONFIRM：
  未确认停在确认卡（ToolApprovalMiddleware 泛型拦截），无工作台 POST；
- 只读查询与草稿保持 AUTO（草稿零扣费，不误升 confirm）；
- ``_TOOLS_REQUIRING_APPROVAL`` 由风险表推导自动包含两 submit；
- FORCE_WORKBENCH_SUBMIT_AUTO 默认关（仅本地调试逃生口，禁上产）；
- 确认卡摘要含 product_id / prompt 脱敏预览 / 模型 / 时长（阶段D 审计可见）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(_BACKEND_ROOT / "packages" / "harness"))

from evoflow.agents.tool_approval_config import (  # noqa: E402
    _TOOLS_REQUIRING_APPROVAL,
    RISK_AUTO,
    RISK_CONFIRM,
    TOOL_RISK_LEVELS,
    format_approval_payload_text,
    parse_user_approval_message,
    summarize_tool_for_approval,
    tool_requires_approval,
    tool_risk_level,
)

_IMAGE_ARGS = {
    "external_ref": "WO-20261108-001",
    "product_id": "prod-12345",
    "prompt": "白色背景，商品居中，节日氛围点缀，高细节主图" + "x" * 200,
    "ratio": "3:4",
}

_VIDEO_ARGS = {
    "external_ref": "WO-20261108-002",
    "product_id": "prod-12345",
    "provider": "供应商A",
    "model": "video-model-x",
    "image_indexes": [0],
    "prompt": "商品旋转展示，柔和灯光，节奏轻快",
    "narration": "开场三秒抓眼球",
    "ratio": "9:16",
    "resolution": "720p",
    "duration": 12,
}


# ── 1) 风险表：submit → confirm，只读/草稿 → auto ───────────────


def test_submit_tools_are_risk_confirm():
    assert TOOL_RISK_LEVELS["workbench_image_submit"] == RISK_CONFIRM
    assert TOOL_RISK_LEVELS["workbench_video_submit"] == RISK_CONFIRM


def test_readonly_and_draft_tools_stay_auto():
    for name in (
        "workbench_products_list",
        "workbench_image_status",
        "workbench_video_options",
        "workbench_video_status",
        "draft_workbench_order",
    ):
        assert TOOL_RISK_LEVELS[name] == RISK_AUTO
        assert tool_risk_level(name, {}) == RISK_AUTO


def test_tool_risk_level_resolves_submits_confirm():
    assert tool_risk_level("workbench_image_submit", _IMAGE_ARGS) == RISK_CONFIRM
    assert tool_risk_level("workbench_video_submit", _VIDEO_ARGS) == RISK_CONFIRM


# ── 2) 推导集合 + requires_approval（确认闸入口）─────────────────


def test_tools_requiring_approval_derivation_contains_submits():
    assert "workbench_image_submit" in _TOOLS_REQUIRING_APPROVAL
    assert "workbench_video_submit" in _TOOLS_REQUIRING_APPROVAL


def test_tool_requires_approval_true_for_submits():
    # 未确认 → True：ToolApprovalMiddleware 会弹确认卡（interrupt），无工作台 POST
    assert tool_requires_approval("workbench_image_submit", _IMAGE_ARGS) is True
    assert tool_requires_approval("workbench_video_submit", _VIDEO_ARGS) is True


def test_tool_requires_approval_false_for_readonly_and_draft():
    assert tool_requires_approval("workbench_products_list", {"search": "x"}) is False
    assert tool_requires_approval("draft_workbench_order", {"requirements": "r"}) is False


# ── 3) FORCE_WORKBENCH_SUBMIT_AUTO：默认关，仅本地调试 ───────────


def test_force_submit_auto_default_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORCE_WORKBENCH_SUBMIT_AUTO", raising=False)
    assert tool_risk_level("workbench_image_submit", _IMAGE_ARGS) == RISK_CONFIRM
    assert tool_requires_approval("workbench_video_submit", _VIDEO_ARGS) is True


def test_force_submit_auto_debug_escape(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FORCE_WORKBENCH_SUBMIT_AUTO", "1")
    assert tool_risk_level("workbench_image_submit", _IMAGE_ARGS) == RISK_AUTO
    monkeypatch.setenv("FORCE_WORKBENCH_SUBMIT_AUTO", "true")
    assert tool_risk_level("workbench_video_submit", _VIDEO_ARGS) == RISK_AUTO


# ── 4) 确认卡摘要（脱敏预览：product_id / prompt 截断 / 模型 / 时长）──


def test_summarize_image_submit_contains_product_and_prompt_preview():
    summary = summarize_tool_for_approval("workbench_image_submit", _IMAGE_ARGS)
    assert "prod-12345" in summary
    assert "WO-20261108-001" in summary
    assert "白色背景" in summary
    assert len(summary) <= 400  # 长_prompt 被截断脱敏
    assert "x" * 200 not in summary


def test_summarize_video_submit_contains_model_and_duration():
    summary = summarize_tool_for_approval("workbench_video_submit", _VIDEO_ARGS)
    assert "prod-12345" in summary
    assert "video-model-x" in summary
    assert "12s" in summary


def test_approval_payload_carries_risk_confirm_and_user_message_round_trip():
    """确认卡 payload（__evf_tool_approval_v1__ 栈）带 confirm 风险与摘要。"""
    import json

    summary = summarize_tool_for_approval("workbench_video_submit", _VIDEO_ARGS)
    text = format_approval_payload_text(
        tool_name="workbench_video_submit",
        tool_call_id="tc_test_1",
        summary=summary,
        risk=RISK_CONFIRM,
    )
    payload = json.loads(text)
    assert payload["risk"] == RISK_CONFIRM
    assert payload["tool_name"] == "workbench_video_submit"
    assert "video-model-x" in payload["summary"]

    # 用户确认消息（壳 buildToolApprovalMessage 同构）可被后端解析（approve 回执路径）
    user_msg = "__evf_tool_approval_v1__: " + json.dumps(
        {"action": "approve", "tool_call_id": "tc_test_1"}, ensure_ascii=False
    )
    parsed = parse_user_approval_message(user_msg)
    assert parsed == {"action": "approve", "tool_call_id": "tc_test_1"}
