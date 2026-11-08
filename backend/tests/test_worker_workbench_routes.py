import asyncio

import pytest
from fastapi import HTTPException

from app.gateway.routers import worker_workbench as routes


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setenv("EVOFLOW_WORKBENCH_TOOL_TOKEN", "local-test-token")
    monkeypatch.setenv("EVOFLOW_WORKBENCH_PREVIEW_KEY", "local-test-preview-key")
    monkeypatch.setattr(routes.ops_summary, "_require_workbench_admin", lambda: None)
    monkeypatch.setattr(routes.ops_summary, "_workbench_auth_headers", lambda: {"Authorization": "Bearer admin"})


def test_worker_guard_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(routes.ops_summary, "_require_workbench_admin", lambda: None)
    with pytest.raises(HTTPException) as error:
        routes._guard("wrong")
    assert error.value.status_code == 403


def test_workbench_preview_ref_is_bound_to_record_and_item():
    preview_ref = "workbench-image://rec_1/2/IMG-123"
    match = routes._IMAGE_REF_RE.fullmatch(preview_ref)
    assert match is not None
    assert (match.group(1), int(match.group(2)), match.group(3)) == ("rec_1", 2, "IMG-123")
    assert routes._IMAGE_REF_RE.fullmatch("workbench-image://rec_1/2/IMG-OTHER")
    assert routes._IMAGE_REF_RE.fullmatch("workbench-image://rec_1/2") is None


def test_product_lookup_only_returns_indexes(monkeypatch):
    monkeypatch.setattr(routes.ops_summary, "_authed_get", lambda path: {
        "assets": [{"id": "pa_1", "name": "三角巾", "image_keys": ["private/key.jpg"],
                    "selling_points": "针织", "knowledge_id": "kb-1"}]})
    result = asyncio.run(routes.products_list(search="", x_evoflow_worker_key="local-test-token"))
    assert result["assets"][0]["images"] == [{"index": 0, "view_angle": "unmarked", "is_primary": True}]
    assert "private/key.jpg" not in repr(result)


def test_image_submit_rejects_invalid_angles_before_workbench_submit(monkeypatch):
    calls = []
    monkeypatch.setattr(routes, "_asset", lambda *args: ({"name": "商品"}, ["image-key"]))
    monkeypatch.setattr(routes.ops_summary, "_authed_post", lambda *a, **kw: calls.append(a))
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.submit_image({"external_ref": "IMG-ORDER-1", "product_id": "pa_1",
                                         "image_indexes": [0], "prompt": "商品白底主图清晰展示",
                                         "ratio": "2:1"},
                                        x_evoflow_worker_key="local-test-token"))
    assert error.value.status_code == 400
    assert calls == []


def test_issued_preview_ref_matches_assigned_task_only(monkeypatch):
    from evoflow.admin import tasks as admin_tasks

    monkeypatch.setattr(admin_tasks, "list_tasks", lambda **_kwargs: {"tasks": [
        {"assigned_to": "emp-image", "description": "external_ref: IMG-123"},
        {"assigned_to": "", "description": "external_ref: IMG-456"},
    ]})
    assert routes._is_issued_preview_ref("rec_1", 0, "IMG-123") is True
    assert routes._is_issued_preview_ref("rec_1", 0, "IMG-456") is False


def test_issued_preview_ref_requires_matching_employee_task(monkeypatch):
    monkeypatch.setattr(routes.ops_summary, "_authed_post", lambda *_args: {
        "external_ref": "IMG-123", "preview_path": "/api/auth/worker-preview/rec_1/0"})
    monkeypatch.setattr(routes, "_is_issued_preview_ref", lambda *_args: False)
    with pytest.raises(HTTPException) as error:
        routes._fetch_workbench_preview("rec_1", 0, expected_ref="IMG-123",
                                        preview_ref="workbench-image://rec_1/0/IMG-123")
    assert error.value.status_code == 404


def test_preview_fetch_checks_record_binding_and_streams_without_cache(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "image/png", "Content-Length": "4"}
        content = b"png!"
        history = []
        url = "http://127.0.0.1:8790/api/auth/worker-preview/rec_1/0"

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, _method, url, headers=None):
            response = FakeResponse()
            response.url = url
            return response

        def get(self, url, headers=None):
            response = FakeResponse()
            response.url = url
            return response

    monkeypatch.setattr(routes, "_is_issued_preview_ref", lambda *_args: True)
    monkeypatch.setattr(routes.ops_summary, "_conf", lambda: ("http://127.0.0.1:8790", "u", "p"))
    monkeypatch.setattr(routes.ops_summary, "_authed_post", lambda path, body: {
        "external_ref": "IMG-123", "preview_path": "/api/auth/worker-preview/rec_1/0",
        "expires": 123456, "signature": "opaque-signature"})
    monkeypatch.setattr(routes.httpx, "Client", FakeClient)
    ref = "workbench-image://rec_1/0/IMG-123"
    response = routes._preview_response("rec_1", 0, expected_ref="IMG-123", preview_ref=ref)
    assert response.body == b"png!"
    assert response.headers["cache-control"] == "private, no-store, max-age=0"

    with pytest.raises(HTTPException) as error:
        routes._fetch_workbench_preview("rec_1", 0, expected_ref="IMG-OTHER", preview_ref=ref)
    assert error.value.status_code == 404


def test_preview_rejects_untrusted_cos_redirect(monkeypatch):
    class RedirectResponse:
        status_code = 307
        headers = {"Location": "https://attacker.invalid/file"}
        url = "http://127.0.0.1:8790/api/auth/worker-preview/rec_1/0"
        history = []

    class RedirectResponseContext(RedirectResponse):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            return RedirectResponseContext()

        def get(self, *_args, **_kwargs):
            return RedirectResponse()

    monkeypatch.setattr(routes, "_is_issued_preview_ref", lambda *_args: True)
    monkeypatch.setattr(routes.ops_summary, "_conf", lambda: ("http://127.0.0.1:8790", "u", "p"))
    monkeypatch.setattr(routes.ops_summary, "_authed_post", lambda *_args: {
        "external_ref": "IMG-123", "preview_path": "/api/auth/worker-preview/rec_1/0",
        "expires": 1, "signature": "sig"})
    monkeypatch.setattr(routes.httpx, "Client", FakeClient)
    with pytest.raises(HTTPException) as error:
        routes._fetch_workbench_preview("rec_1", 0, expected_ref="IMG-123")
    assert error.value.status_code == 502


def test_browser_preview_resolves_legacy_path_as_admin(monkeypatch):
    monkeypatch.setattr(routes, "require_org_admin", lambda _request: None)
    monkeypatch.setattr(routes.ops_summary, "_authed_post", lambda *_args: {
        "external_ref": "WO-LEGACY-1"})
    monkeypatch.setattr(routes, "_is_issued_preview_ref", lambda *_args: False)
    monkeypatch.setattr(routes, "_preview_response", lambda rid, index, **kwargs: {
        "record_id": rid, "item_index": index, **kwargs})
    result = asyncio.run(routes.browser_image_preview(
        "rec_1", 0, request=object(), external_ref=""))
    assert result["expected_ref"] == "WO-LEGACY-1"
    assert result["preview_ref"] == ""


def test_browser_preview_with_ref_requires_assigned_task(monkeypatch):
    monkeypatch.setattr(routes, "require_org_admin", lambda _request: None)
    monkeypatch.setattr(routes.ops_summary, "_authed_post", lambda *_args: {"external_ref": "IMG-123"})
    monkeypatch.setattr(routes, "_is_issued_preview_ref", lambda *_args: False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.browser_image_preview("rec_1", 0, request=object(), external_ref="IMG-123"))
    assert error.value.status_code == 404


def test_worker_image_preview_requires_matching_opaque_ref(monkeypatch):
    monkeypatch.setattr(routes, "_preview_response", lambda record_id, item_index, **kwargs: {
        "record_id": record_id, "item_index": item_index, **kwargs})
    result = asyncio.run(routes.image_preview_bytes(
        "rec_1", 0, x_evoflow_worker_key="local-test-token",
        x_evoflow_image_ref="workbench-image://rec_1/0/IMG-123",
        x_evoflow_external_ref="IMG-123"))
    assert result["preview_ref"] == "workbench-image://rec_1/0/IMG-123"
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.image_preview_bytes(
            "rec_1", 0, x_evoflow_worker_key="local-test-token",
            x_evoflow_image_ref="workbench-image://rec_1/0/IMG-OTHER", x_evoflow_external_ref="IMG-123"))
    assert error.value.status_code == 404


def test_browser_preview_requires_org_admin_and_issued_task_ref(monkeypatch):
    monkeypatch.setattr(routes, "require_org_admin", lambda _request: None)
    monkeypatch.setattr(routes, "_is_issued_preview_ref", lambda *args: args == ("rec_1", 0, "IMG-123"))
    monkeypatch.setattr(routes.ops_summary, "_authed_post", lambda _path, _body: {"external_ref": "IMG-123"})
    monkeypatch.setattr(routes, "_preview_response", lambda record_id, item_index, **kwargs: {
        "record_id": record_id, "item_index": item_index, **kwargs})
    result = asyncio.run(routes.browser_image_preview(
        "rec_1", 0, request=object(), external_ref="IMG-123"))
    assert result["expected_ref"] == "IMG-123"
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.browser_image_preview(
            "rec_1", 0, request=object(), external_ref="IMG-OTHER"))
    assert error.value.status_code == 404


def test_video_submit_checks_current_capabilities(monkeypatch):
    monkeypatch.setattr(routes, "_asset", lambda *args: ({"name": "商品"}, ["image-key"]))
    monkeypatch.setattr(routes.ops_summary, "_authed_get", lambda _path: {
        "video_providers": [{"name": "当前供应商", "models": [{
            "id": "model-a", "durations": [8], "ratios": ["9:16"],
            "resolutions": ["720p"], "max_images": 1,
        }]}]})
    submitted = []
    monkeypatch.setattr(routes.ops_summary, "_authed_post", lambda path, payload: submitted.append(payload) or {
        "id": "job-1", "title": "商品视频", "status": "queued"})
    body = {"external_ref": "VID-ORDER-1", "product_id": "pa_1", "image_indexes": [0],
            "prompt": "商品展示并平滑旋转", "provider": "当前供应商", "model": "model-a",
            "ratio": "9:16", "resolution": "720p", "duration": 8}
    result = asyncio.run(routes.submit_video(body, x_evoflow_worker_key="local-test-token"))
    assert result["id"] == "job-1"
    assert result["select_layer"] == "manual"  # 显式 [0] → manual，不跑自动
    assert submitted[0]["submission_key"].startswith("evoflow:")
    body["model"] = "not-configured"
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.submit_video(body, x_evoflow_worker_key="local-test-token"))
    assert error.value.status_code == 400
    assert len(submitted) == 1


# ── 档案参考图自动优选（1.4.11 T1/T2/T3/T5/T6/T7/T8/T9）────────────


@pytest.fixture()
def no_model_layers(monkeypatch):
    """L1/L2 生产函数钉死为 boom：凡被调用即测试失败（L0/forced0 不许碰模型）。"""
    monkeypatch.setattr(routes.archive_ref_pick, "production_llm_fn",
                        lambda *_a, **_k: pytest.fail("L1 不应被调用"))
    monkeypatch.setattr(routes.archive_ref_pick, "cached_vision_fn",
                        lambda *_a, **_k: (lambda *_ca, **_ck: pytest.fail("L2 不应被调用")))
    for flag in ("FORCE_PRIMARY_IMAGE", "ARCHIVE_REF_L1", "ARCHIVE_REF_L2",
                 "ARCHIVE_REF_PICK_DEADLINE_MS"):
        monkeypatch.delenv(flag, raising=False)


def _assets_get(assets):
    def get(path):
        if path == "/api/product-assets":
            return {"assets": assets}
        raise AssertionError(f"unexpected GET {path}")

    return get


def test_t1_image_submit_auto_picks_white_background(monkeypatch, no_model_layers):
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1", "k2"], "view_angles": ["scene", "", "white"]}
    monkeypatch.setattr(routes.ops_summary, "_authed_get", _assets_get([asset]))
    posts = []
    monkeypatch.setattr(routes.ops_summary, "_authed_post",
                        lambda path, payload: posts.append((path, payload)) or {"id": "rec-2"})
    result = asyncio.run(routes.submit_image(
        {"external_ref": "IMG-AUTO-1", "product_id": "pa_1",
         "prompt": "商品白底主图清晰展示"}, x_evoflow_worker_key="local-test-token"))
    assert result["selected_indexes"] == [2]
    assert result["select_layer"] == "L0"
    assert result["select_reason"]
    draft_path, draft = posts[0]
    assert draft_path == "/api/records/draft"
    assert draft["params"]["images"] == ["k2"]  # 真正用了白底那张


def test_t2_image_submit_explicit_index_is_manual(monkeypatch, no_model_layers):
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1", "k2"], "view_angles": ["scene", "", "white"]}
    monkeypatch.setattr(routes.ops_summary, "_authed_get", _assets_get([asset]))
    posts = []
    monkeypatch.setattr(routes.ops_summary, "_authed_post",
                        lambda path, payload: posts.append((path, payload)) or {"id": "rec-3"})
    result = asyncio.run(routes.submit_image(
        {"external_ref": "IMG-AUTO-2", "product_id": "pa_1", "image_indexes": [1],
         "prompt": "商品白底主图清晰展示"}, x_evoflow_worker_key="local-test-token"))
    assert result["select_layer"] == "manual"
    assert result["selected_indexes"] == [1]
    assert posts[0][1]["params"]["images"] == ["k1"]


def test_t3_image_submit_rejects_two_explicit_indexes(monkeypatch, no_model_layers):
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1", "k2"], "view_angles": []}
    monkeypatch.setattr(routes.ops_summary, "_authed_get", _assets_get([asset]))
    posts = []
    monkeypatch.setattr(routes.ops_summary, "_authed_post",
                        lambda path, payload: posts.append((path, payload)) or {"id": "rec-x"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.submit_image(
            {"external_ref": "IMG-AUTO-3", "product_id": "pa_1", "image_indexes": [2, 3],
             "prompt": "商品白底主图清晰展示"}, x_evoflow_worker_key="local-test-token"))
    assert error.value.status_code == 400
    assert posts == []


def test_t5_image_submit_empty_archive_never_creates_draft(monkeypatch, no_model_layers):
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "", "image_keys": [],
             "view_angles": []}
    monkeypatch.setattr(routes.ops_summary, "_authed_get", _assets_get([asset]))
    posts = []
    monkeypatch.setattr(routes.ops_summary, "_authed_post",
                        lambda path, payload: posts.append((path, payload)) or {"id": "rec-x"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.submit_image(
            {"external_ref": "IMG-AUTO-4", "product_id": "pa_1",
             "prompt": "商品白底主图清晰展示"}, x_evoflow_worker_key="local-test-token"))
    assert error.value.status_code == 400
    assert "补图" in error.value.detail
    assert posts == []  # 禁止空提交扣费


def test_t6_image_submit_invalid_explicit_index_is_400_not_forced0(monkeypatch, no_model_layers):
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1"], "view_angles": []}
    monkeypatch.setattr(routes.ops_summary, "_authed_get", _assets_get([asset]))
    monkeypatch.setattr(routes.ops_summary, "_authed_post",
                        lambda *_a, **_k: pytest.fail("不应提交"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.submit_image(
            {"external_ref": "IMG-AUTO-5", "product_id": "pa_1", "image_indexes": [99],
             "prompt": "商品白底主图清晰展示"}, x_evoflow_worker_key="local-test-token"))
    assert error.value.status_code == 400


def test_t7_force_primary_env_falls_back_to_index_zero(monkeypatch, no_model_layers):
    monkeypatch.setenv("FORCE_PRIMARY_IMAGE", "1")
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1", "k2"], "view_angles": ["scene", "", "white"]}
    monkeypatch.setattr(routes.ops_summary, "_authed_get", _assets_get([asset]))
    posts = []
    monkeypatch.setattr(routes.ops_summary, "_authed_post",
                        lambda path, payload: posts.append((path, payload)) or {"id": "rec-7"})
    result = asyncio.run(routes.submit_image(
        {"external_ref": "IMG-AUTO-6", "product_id": "pa_1",
         "prompt": "商品白底主图清晰展示"}, x_evoflow_worker_key="local-test-token"))
    assert result["selected_indexes"] == [0]  # 有白底也回退主图
    assert result["select_layer"] == "forced0"
    assert posts[0][1]["params"]["images"] == ["k0"]


def test_image_submit_dedup_replay_carries_pick_fields(monkeypatch, no_model_layers):
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1", "k2"], "view_angles": ["scene", "", "white"]}
    record = {"id": "rec-d", "feature": "detail_main", "external_ref": "IMG-AUTO-7",
              "status": "queued", "running": False, "items": [],
              "params": {"images": ["k2"], "requirement": "商品白底主图清晰展示",
                         "ratio": "3:4", "product_id": "", "product_name": "三角巾",
                         "use_knowledge": False}}

    def get(path):
        assert path == "/api/product-assets" or path == "/api/records/rec-d"
        return record if path.endswith("rec-d") else {"assets": [asset]}

    posts = []

    def post(path, payload):
        posts.append(path)
        return {"id": "rec-d", "deduped": True}

    monkeypatch.setattr(routes.ops_summary, "_authed_get", get)
    monkeypatch.setattr(routes.ops_summary, "_authed_post", post)
    result = asyncio.run(routes.submit_image(
        {"external_ref": "IMG-AUTO-7", "product_id": "pa_1",
         "prompt": "商品白底主图清晰展示"}, x_evoflow_worker_key="local-test-token"))
    assert result["deduped"] is True
    assert result["selected_indexes"] == [2]  # 幂等回放仍回显已选下标与层
    assert result["select_layer"] == "L0"


def _video_env(monkeypatch, assets, max_images):
    def get(path):
        if path == "/api/product-assets":
            return {"assets": assets}
        if path == "/api/video/creator/capabilities":
            return {"video_providers": [{"name": "当前供应商", "models": [{
                "id": "model-a", "durations": [8], "ratios": ["9:16"],
                "resolutions": ["720p"], "max_images": max_images}]}]}
        raise AssertionError(f"unexpected GET {path}")

    posts = []

    def post(path, payload):
        posts.append((path, payload))
        return {"id": "job-1", "title": "商品视频", "status": "queued"}

    monkeypatch.setattr(routes.ops_summary, "_authed_get", get)
    monkeypatch.setattr(routes.ops_summary, "_authed_post", post)
    return posts


def _video_body(**extra):
    body = {"external_ref": "VID-AUTO-1", "product_id": "pa_1",
            "prompt": "商品展示并平滑旋转", "provider": "当前供应商", "model": "model-a",
            "ratio": "9:16", "resolution": "720p", "duration": 8}
    body.update(extra)
    return body


def test_t8_video_submit_auto_picks_distinct_angles(monkeypatch, no_model_layers):
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1", "k2", "k3"],
             "view_angles": ["scene", "side", "back", "scene"]}
    posts = _video_env(monkeypatch, [asset], max_images=3)
    result = asyncio.run(routes.submit_video(
        _video_body(), x_evoflow_worker_key="local-test-token"))
    assert result["selected_indexes"] == [0, 1, 2]  # 封面 + 异视角（拍板 D）
    assert result["select_layer"] == "L0"
    job_path, job = [p for p in posts if p[0] == "/api/video/creator/jobs"][0]
    assert job["image_keys"] == ["k0", "k1", "k2"]


def test_t9_video_submit_single_angle_fills_same_angle(monkeypatch, no_model_layers):
    # 实现口径：仅 1 个视角时允许同视角按次序补齐（L0 完成，不调模型）
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1", "k2", "k3"],
             "view_angles": ["front", "front", "front", "front"]}
    posts = _video_env(monkeypatch, [asset], max_images=3)
    result = asyncio.run(routes.submit_video(
        _video_body(), x_evoflow_worker_key="local-test-token"))
    assert result["selected_indexes"] == [0, 1, 2]
    assert all(0 <= i < 4 for i in result["selected_indexes"])  # 不得选无效下标
    job = [p for p in posts if p[0] == "/api/video/creator/jobs"][0][1]
    assert job["image_keys"] == ["k0", "k1", "k2"]


def test_video_submit_single_image_model_auto_picks_cover_only(monkeypatch, no_model_layers):
    # max_images=1 → want_count=1 → video_cover：优先场景那张
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "",
             "image_keys": ["k0", "k1"], "view_angles": ["white", "lifestyle"]}
    posts = _video_env(monkeypatch, [asset], max_images=1)
    result = asyncio.run(routes.submit_video(
        _video_body(), x_evoflow_worker_key="local-test-token"))
    assert result["selected_indexes"] == [1]
    assert result["select_layer"] == "L0"
    job = [p for p in posts if p[0] == "/api/video/creator/jobs"][0][1]
    assert job["image_keys"] == ["k1"]


def test_video_submit_empty_archive_rejects_before_job(monkeypatch, no_model_layers):
    asset = {"id": "pa_1", "name": "三角巾", "knowledge_id": "", "image_keys": [],
             "view_angles": []}
    posts = _video_env(monkeypatch, [asset], max_images=3)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.submit_video(
            _video_body(), x_evoflow_worker_key="local-test-token"))
    assert error.value.status_code == 400
    assert "补图" in error.value.detail
    assert [p for p in posts if p[0] == "/api/video/creator/jobs"] == []
