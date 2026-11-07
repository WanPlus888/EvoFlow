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
    assert submitted[0]["submission_key"].startswith("evoflow:")
    body["model"] = "not-configured"
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.submit_video(body, x_evoflow_worker_key="local-test-token"))
    assert error.value.status_code == 400
    assert len(submitted) == 1
