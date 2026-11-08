"""档案参考图自动优选纯函数测例（T1-T10 中不涉网关/工具层的部分）。

对应派活 steps 阶段 F：
- T1 做图省略 indexes 命中白底；T2 显式 manual 不调模型；T3 做图多下标拒绝；
- T4 全 unmarked + L1/L2 失败 → forced0；T6 非法下标拒绝（不静默改 0）；
- T7 FORCE_PRIMARY 兜底；T8/T9 视频多图异视角；T10 L2 超预算降级。
"""

import time

import pytest

from evoflow.collab.archive_ref_picker import (
    NoImagesError,
    PickResult,
    resolve_reference_indexes,
)


def _meta(*angles: str) -> list[dict]:
    return [{"index": i, "view_angle": a, "is_primary": i == 0} for i, a in enumerate(angles)]


def _boom(*_args, **_kwargs):
    raise AssertionError("模型层不应被调用")


# ── L0 规则层 ────────────────────────────────────────────────────


def test_t1_image_main_picks_unique_white_background():
    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("scene", "", "white"), want_count=1, llm_fn=_boom, vision_fn=_boom)
    assert result.indexes == [2]
    assert result.layer == "L0"
    assert len(result.indexes) == 1


def test_l0_detail_task_prefers_detail_angle():
    result = resolve_reference_indexes(task_kind="image_detail", images_meta=_meta("front", "细节特写"), want_count=1, llm_fn=_boom, vision_fn=_boom)
    assert result.indexes == [1]
    assert result.layer == "L0"


def test_l0_video_cover_prefers_scene():
    result = resolve_reference_indexes(task_kind="video_cover", images_meta=_meta("white", "lifestyle"), want_count=1, llm_fn=_boom, vision_fn=_boom)
    assert result.indexes == [1]
    assert result.layer == "L0"


def test_single_image_archive_short_circuits():
    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("unmarked"), want_count=1)
    assert result.indexes == [0]
    assert result.layer == "L0"


# ── 显式指定 / 非法输入（T2 / T3 / T6 / T5）──────────────────────


def test_t2_explicit_index_is_manual_and_skips_models():
    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("scene", "", "white"), explicit_indexes=[2], want_count=1, llm_fn=_boom, vision_fn=_boom)
    assert result.indexes == [2]
    assert result.layer == "manual"


def test_t3_image_task_rejects_multiple_explicit_indexes():
    with pytest.raises(ValueError):
        resolve_reference_indexes(task_kind="image_main", images_meta=_meta("a", "b", "c"), explicit_indexes=[2, 3], want_count=1)


def test_t6_invalid_explicit_index_raises_not_forced0():
    with pytest.raises(ValueError):
        resolve_reference_indexes(task_kind="image_main", images_meta=_meta("a", "b"), explicit_indexes=[99], want_count=1)


def test_t5_empty_archive_raises_no_images():
    with pytest.raises(NoImagesError):
        resolve_reference_indexes(task_kind="image_main", images_meta=[], want_count=1)


def test_explicit_video_indexes_keep_user_order():
    result = resolve_reference_indexes(task_kind="video_multi", images_meta=_meta("front", "side", "back"), explicit_indexes=[2, 1], want_count=2)
    assert result.indexes == [2, 1]
    assert result.layer == "manual"


# ── 降级链（T4 / T10）────────────────────────────────────────────


def test_t4_all_unmarked_with_failing_layers_falls_back_to_forced0():
    result = resolve_reference_indexes(
        task_kind="image_main", images_meta=_meta("unmarked", "", "other"), want_count=1, llm_fn=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down")), vision_fn=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down"))
    )
    assert result.indexes == [0]
    assert result.layer == "forced0"


def test_l1_success_on_unmarked_archive():
    def llm(payload):
        assert payload["images"][0]["index"] == 0  # 只传元数据，无像素
        return {"indexes": [1], "reason": "第二张构图更稳"}

    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("unmarked", "unmarked"), want_count=1, llm_fn=llm, vision_fn=_boom)
    assert result.indexes == [1]
    assert result.layer == "L1"
    assert "构图" in result.reason


def test_l1_invalid_output_degrades_to_l2():
    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("unmarked", "unmarked"), want_count=1, llm_fn=lambda *_a, **_k: {"indexes": [99]}, vision_fn=lambda candidates: {c.index: float(c.index) for c in candidates})
    assert result.indexes == [1]
    assert result.layer == "L2"


def test_t10_slow_llm_discarded_by_deadline_then_forced0():
    def slow_llm(_payload):
        time.sleep(0.12)
        return {"indexes": [1], "reason": "late"}

    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("unmarked", "unmarked"), want_count=1, llm_fn=slow_llm, vision_fn=None, deadline_ms=40)
    assert result.indexes == [0]
    assert result.layer == "forced0"


def test_t10_slow_vision_discarded_by_deadline():
    def slow_vision(_candidates):
        time.sleep(0.12)
        return {0: 1.0, 1: 9.0}

    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("unmarked", "unmarked"), want_count=1, llm_fn=None, vision_fn=slow_vision, deadline_ms=40)
    assert result.indexes == [0]
    assert result.layer == "forced0"


# ── 总开关（T7）──────────────────────────────────────────────────


def test_t7_force_primary_overrides_everything():
    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("scene", "", "white"), want_count=1, force_primary=True, llm_fn=_boom, vision_fn=_boom)
    assert result.indexes == [0]
    assert result.layer == "forced0"


def test_l1_l2_disabled_tie_with_signal_takes_first_index():
    # A.1 例外：有信号的同分平局 + 两层全关 → 取靠前下标（L0）
    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("white", "白底"), want_count=1, enable_l1=False, enable_l2=False)
    assert result.indexes == [0]
    assert result.layer == "L0"


def test_l1_l2_disabled_unmarked_still_forced0():
    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("unmarked", "unmarked"), want_count=1, enable_l1=False, enable_l2=False)
    assert result.indexes == [0]
    assert result.layer == "forced0"


# ── 视频多图（T8 / T9）───────────────────────────────────────────


def test_t8_video_multi_prefers_distinct_view_angles():
    result = resolve_reference_indexes(task_kind="video_multi", images_meta=_meta("scene", "side", "back", "scene"), want_count=3, llm_fn=_boom, vision_fn=_boom)
    assert result.indexes == [0, 1, 2]  # 封面 scene + 异视角 side/back
    assert result.layer == "L0"
    angles = ["scene", "side", "back", "scene"]
    picked = {angles[i] for i in result.indexes}
    assert picked == {"scene", "side", "back"}  # 视角互异（拍板 D）


def test_t9_video_multi_single_angle_fills_same_angle_at_l0():
    # 实现口径（写进注释）：仅 1 个视角时允许同视角按次序补齐（拍板 D 的
    # 「不足再降」分支），在 L0 完成，无需模型层。
    result = resolve_reference_indexes(task_kind="video_multi", images_meta=_meta("scene", "scene", "scene", "scene"), want_count=3, llm_fn=_boom, vision_fn=_boom)
    assert result.indexes == [0, 1, 2]
    assert result.layer == "L0"


def test_t9_video_multi_unmarked_failing_layers_forced0():
    # 无任何视角信号 + 模型层全失败 → forced0 [0]（少于 3 张，均为有效下标）
    result = resolve_reference_indexes(
        task_kind="video_multi", images_meta=_meta("unmarked", "", "other", "none"), want_count=3, llm_fn=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down")), vision_fn=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down"))
    )
    assert result.indexes == [0]
    assert result.layer == "forced0"


def test_t9_video_multi_unmarked_l1_can_fill():
    def llm(_payload):
        return {"indexes": [0, 2, 3], "reason": "按描述相关性选 3 张"}

    result = resolve_reference_indexes(task_kind="video_multi", images_meta=_meta("unmarked", "", "other", "none"), want_count=3, llm_fn=llm, vision_fn=_boom)
    assert result.indexes == [0, 2, 3]
    assert result.layer == "L1"


def test_video_multi_l2_scores_drive_distinct_fill():
    result = resolve_reference_indexes(task_kind="video_multi", images_meta=_meta("unmarked", "unmarked", "unmarked", "unmarked"), want_count=3, llm_fn=None, vision_fn=lambda candidates: {0: 5.0, 1: 9.0, 2: 7.0, 3: 1.0})
    assert result.indexes == [1, 2, 0]  # 分数排序：9 > 7 > 5（同视角不足时按分补齐）
    assert result.layer == "L2"


def test_video_multi_archive_smaller_than_want_uses_all():
    result = resolve_reference_indexes(task_kind="video_multi", images_meta=_meta("scene", "side"), want_count=3, llm_fn=_boom, vision_fn=_boom)
    assert result.indexes == [0, 1]
    assert result.layer == "L0"


def test_task_kind_coercion_between_cover_and_multi():
    cover = resolve_reference_indexes(task_kind="video_cover", images_meta=_meta("scene", "side", "back"), want_count=3, llm_fn=_boom, vision_fn=_boom)
    assert cover.layer == "L0" and cover.indexes == [0, 1, 2]  # want>1 → multi
    single = resolve_reference_indexes(task_kind="video_multi", images_meta=_meta("scene", "side"), want_count=1, llm_fn=_boom, vision_fn=_boom)
    assert single.layer == "L0" and single.indexes == [0]  # want==1 → cover


def test_unknown_task_kind_rejected():
    with pytest.raises(ValueError):
        resolve_reference_indexes(task_kind="mystery", images_meta=_meta("a"), want_count=1)


def test_pick_result_reason_is_bounded():
    result = resolve_reference_indexes(task_kind="image_main", images_meta=_meta("white", "scene"), want_count=1)
    assert isinstance(result, PickResult)
    assert len(result.reason) <= 200
