"""一句话 → 结构化工单草稿 纯单元测例（无 DB、无网络）。"""

from datetime import datetime

from evoflow.collab.workbench_order_draft import (
    new_external_ref,
    parse_one_liner_to_order_draft,
)


FIXED_NOW = datetime(2026, 11, 7, 7, 45, 0)


def test_image_scene_eight_mains_budget_30():
    draft = parse_one_liner_to_order_draft(
        "给这个碎花连衣裙出 8 张主图，预算 30", now=FIXED_NOW
    )
    assert draft["type"] == "image"
    assert "碎花连衣裙" in draft["product"]
    assert "8" in draft["qty"]
    assert "30" in draft["budget"]
    assert draft["assigned_role"] == "tuantu-op"
    assert draft["external_ref"] in draft["description"]
    assert "套图" in draft["description"]
    assert "batch/jobs" in draft["description"]
    assert draft["needs_confirm"] is False


def test_video_scene_15s_koubo():
    draft = parse_one_liner_to_order_draft("按卖点拍 15 秒口播", now=FIXED_NOW)
    assert draft["type"] == "video"
    assert draft["assigned_role"] == "shipin-op"
    assert "短视频" in draft["description"]
    assert "product" in draft["needs_confirm_fields"]


def test_tuwen_xiaohongshu_three():
    draft = parse_one_liner_to_order_draft("出 3 篇小红书图文", now=FIXED_NOW)
    assert draft["type"] == "tuwen"
    assert "3" in draft["qty"]


def test_custom_fallback_and_confirm():
    draft = parse_one_liner_to_order_draft("处理一下", now=FIXED_NOW)
    assert draft["type"] == "custom"
    assert draft["needs_confirm"] is True


def test_external_ref_format_stable_with_fixed_now():
    ref = new_external_ref(now=FIXED_NOW)
    assert ref == "EV-20261107-074500"


def test_format_description_omits_empty_budget_line():
    draft = parse_one_liner_to_order_draft("给这个杯子出 4 张主图", now=FIXED_NOW)
    assert draft["budget"] == ""
    assert "预算上限" not in draft["description"]
