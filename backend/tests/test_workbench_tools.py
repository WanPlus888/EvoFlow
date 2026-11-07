import json
import urllib.error

import pytest

from evoflow.agents.lead_agent.intent_tool_profile import flat_bound_tool_names_for_session_mode
from evoflow.tools.builtins import workbench_tools as tools
from evoflow.tools.tool_catalog import is_role_editor_configurable_tool
from evoflow.tools.tools import get_builtin_tools

WORKBENCH_TOOLS = {
    "workbench_products_list",
    "workbench_image_submit",
    "workbench_image_status",
    "workbench_video_options",
    "workbench_video_submit",
    "workbench_video_status",
}


def test_workbench_tools_are_bindable_for_employee_runs():
    assert WORKBENCH_TOOLS.issubset(set(flat_bound_tools_for_agent()))
    assert all(is_role_editor_configurable_tool(name) for name in WORKBENCH_TOOLS)


def flat_bound_tools_for_agent():
    return flat_bound_tool_names_for_session_mode("agent")


def test_view_image_is_agent_mode_bindable():
    assert "view_image" in flat_bound_tool_names_for_session_mode("agent")
    assert is_role_editor_configurable_tool("view_image")


def test_builtin_catalog_registers_workbench_tools():
    names = {tool.name for tool in get_builtin_tools()}
    assert WORKBENCH_TOOLS <= names
    assert "view_image" in names


def test_worker_request_refuses_missing_internal_token(monkeypatch):
    monkeypatch.setenv("EVOFLOW_GATEWAY_URL", "http://127.0.0.1:8012")
    monkeypatch.delenv("EVOFLOW_WORKBENCH_TOOL_TOKEN", raising=False)
    result = tools._worker_request("/api/opsboard/worker/products")
    assert result == {"ok": False, "error": "工作台工具未配置访问凭据"}


def test_worker_request_rejects_non_loopback_gateway(monkeypatch):
    monkeypatch.setenv("EVOFLOW_GATEWAY_URL", "https://example.invalid")
    monkeypatch.setenv("EVOFLOW_WORKBENCH_TOOL_TOKEN", "test-token")
    result = tools._worker_request("/api/opsboard/worker/products")
    assert result == {"ok": False, "error": "工作台工具仅允许访问本机 Gateway"}


def test_worker_request_only_allows_fixed_route_prefix(monkeypatch):
    monkeypatch.setenv("EVOFLOW_GATEWAY_URL", "http://127.0.0.1:8012")
    monkeypatch.setenv("EVOFLOW_WORKBENCH_TOOL_TOKEN", "test-token")
    result = tools._worker_request("/api/auth/users")
    assert result == {"ok": False, "error": "工作台工具只允许固定操作"}


def test_image_submit_enforces_reference_limit_without_network(monkeypatch):
    monkeypatch.setattr(tools, "_worker_request", lambda *args, **kwargs: pytest.fail("unexpected request"))
    result = json.loads(tools.workbench_image_submit.func(
        external_ref="IMG-ORDER-1", product_id="pa_abc123", prompt="商品白底主图清晰展示",
        ratio="2:1"))
    assert result["ok"] is False
    assert "图片比例无效" == result["error"]


def test_image_submit_preserves_idempotency_reference(monkeypatch):
    captured = {}

    def request(path, *, method="GET", payload=None):
        captured.update(path=path, method=method, payload=payload)
        return {"ok": True, "id": "rec-123"}

    monkeypatch.setattr(tools, "_worker_request", request)
    result = json.loads(tools.workbench_image_submit.func(
        external_ref="IMG-ORDER-1", product_id="pa_abc123", prompt="商品白底主图清晰展示"))
    assert result["id"] == "rec-123"
    assert captured["path"] == "/api/opsboard/worker/images"
    assert captured["payload"]["external_ref"] == "IMG-ORDER-1"


def test_image_status_sends_external_ref_in_header(monkeypatch):
    captured = {}

    def request(path, *, method="GET", payload=None, external_ref=""):
        captured.update(path=path, method=method, external_ref=external_ref)
        return {"ok": True, "id": "rec-123", "external_ref": external_ref}

    monkeypatch.setattr(tools, "_worker_request", request)
    result = json.loads(tools.workbench_image_status.func(
        record_id="rec-123", external_ref="IMG-ORDER-1"))
    assert result["ok"] is True
    assert captured == {"path": "/api/opsboard/worker/images/rec-123",
                        "method": "GET", "external_ref": "IMG-ORDER-1"}


def test_video_submit_requires_explicit_workbench_model(monkeypatch):
    captured = {}
    monkeypatch.setattr(tools, "_worker_request", lambda path, **kwargs: captured.update(
        path=path, **kwargs) or {"ok": True})
    tools.workbench_video_submit.func(
        external_ref="VID-ORDER-1", product_id="pa_abc123", prompt="商品展示并平滑旋转",
        provider="工作台默认供应商", model="configured-model")
    assert captured["payload"]["provider"] == "工作台默认供应商"
    assert captured["payload"]["model"] == "configured-model"


def test_http_error_body_is_not_returned(monkeypatch):
    monkeypatch.setenv("EVOFLOW_GATEWAY_URL", "http://127.0.0.1:8012")
    monkeypatch.setenv("EVOFLOW_WORKBENCH_TOOL_TOKEN", "test-token")

    def fail(_request, timeout):
        raise urllib.error.HTTPError("http://127.0.0.1:8012/api/opsboard/worker/products", 403,
                                     "forbidden", {}, None)

    monkeypatch.setattr(tools.urllib.request, "urlopen", fail)
    result = tools._worker_request("/api/opsboard/worker/products")
    assert result == {"ok": False, "error": "工作台请求失败（HTTP 403）"}
