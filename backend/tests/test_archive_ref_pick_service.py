"""网关侧优选接线（archive_ref_pick）单元测例：开关 / JSON 解析 / L2 缓存。"""

import pytest

from app.gateway.routers import archive_ref_pick as svc


def test_flags_default_and_overrides(monkeypatch):
    for flag in ("FORCE_PRIMARY_IMAGE", "ARCHIVE_REF_L1", "ARCHIVE_REF_L2", "ARCHIVE_REF_PICK_DEADLINE_MS"):
        monkeypatch.delenv(flag, raising=False)
    assert svc.force_primary_enabled() is False  # 总开关默认关
    assert svc.l1_enabled() is True  # L1 默认在链上
    assert svc.l2_enabled() is True  # L2 默认在链上
    assert svc.deadline_ms() == 10000
    monkeypatch.setenv("FORCE_PRIMARY_IMAGE", "1")
    monkeypatch.setenv("ARCHIVE_REF_L1", "0")
    monkeypatch.setenv("ARCHIVE_REF_L2", "false")
    monkeypatch.setenv("ARCHIVE_REF_PICK_DEADLINE_MS", "3000")
    assert svc.force_primary_enabled() is True
    assert svc.l1_enabled() is False
    assert svc.l2_enabled() is False
    assert svc.deadline_ms() == 3000


def test_extract_json_object_tolerates_fences_and_chatter():
    assert svc._extract_json_object('{"indexes": [1]}') == {"indexes": [1]}
    assert svc._extract_json_object('```json\n{"scores": {"0": 8}}\n```') == {"scores": {"0": 8}}
    assert svc._extract_json_object('好的，结果是 {"indexes": [2], "reason": "白底"} 以上') == {"indexes": [2], "reason": "白底"}
    with pytest.raises(ValueError):
        svc._extract_json_object("没有任何 JSON")


def test_cached_vision_fn_hits_cache_without_second_call(monkeypatch):
    svc._L2_SCORE_CACHE.clear()
    calls = []

    def fake_score(product_id, model, task_kind, candidates):
        calls.append([c["index"] for c in candidates])
        return {c["index"]: float(c["index"]) + 5.0 for c in candidates}

    monkeypatch.setattr(svc, "_vision_model_name", lambda: "vision-m")
    monkeypatch.setattr(svc, "_score_candidates", fake_score)
    vision_fn = svc.cached_vision_fn("pa_1", "image_main")
    candidates = [{"index": 0, "image_key": "k0"}, {"index": 1, "image_key": "k1"}]

    first = vision_fn(candidates)
    assert first == {0: 5.0, 1: 6.0}
    assert calls == [[0, 1]]

    # 第二次（新闭包、同 asset/key/model/task）：全命中缓存，不再发调用
    second = svc.cached_vision_fn("pa_1", "image_main")(candidates)
    assert second == first
    assert calls == [[0, 1]]  # 命中缓存不计费

    # 部分命中：只对未缓存的候选发起调用
    third = svc.cached_vision_fn("pa_1", "image_main")([*candidates, {"index": 2, "image_key": "k2"}])
    assert third == {0: 5.0, 1: 6.0, 2: 7.0}
    assert calls == [[0, 1], [2]]


def test_cached_vision_fn_without_image_url_template_raises(monkeypatch):
    # 未配置取图模板 → 真实 _score_candidates 在取图一步抛 RuntimeError（L2 层失败，
    # 由 picker 降级），且发生在任何模型调用之前。
    svc._L2_SCORE_CACHE.clear()
    monkeypatch.delenv("ARCHIVE_REF_IMAGE_URL_TEMPLATE", raising=False)
    monkeypatch.setattr(svc, "_vision_model_name", lambda: "vision-m")
    with pytest.raises(RuntimeError):
        svc.cached_vision_fn("pa_1", "image_main")([{"index": 0, "image_key": "k0"}])
