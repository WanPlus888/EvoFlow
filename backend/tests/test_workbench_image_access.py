import pytest

from evoflow.tools.builtins import workbench_image_access as access


def test_workbench_image_ref_requires_record_index_and_external_ref():
    assert access.parse_workbench_image_ref("workbench-image://rec_1/0/IMG-123") == ("rec_1", 0, "IMG-123")
    assert access.parse_workbench_image_ref("workbench-image://rec_1/0") is None
    assert access.parse_workbench_image_ref("workbench-image://rec_1/0/IMG-123?ticket=secret") is None
    assert access.parse_workbench_image_ref("workbench-image://rec_1/../IMG-123") is None


def test_gateway_image_endpoint_requires_loopback_gateway(monkeypatch):
    monkeypatch.setenv("EVOFLOW_GATEWAY_URL", "https://example.invalid")
    monkeypatch.setenv("EVOFLOW_WORKBENCH_TOOL_TOKEN", "internal")
    with pytest.raises(ValueError, match="local Gateway"):
        access.read_workbench_image_ref("workbench-image://rec_1/0/IMG-123")


def test_gateway_image_endpoint_accepts_only_workbench_preview_path(monkeypatch):
    monkeypatch.setenv("EVOFLOW_GATEWAY_URL", "http://127.0.0.1:8012")
    monkeypatch.setenv("EVOFLOW_WORKBENCH_TOOL_TOKEN", "internal")
    with pytest.raises(ValueError, match="not configured"):
        access._gateway_request("/api/opsboard/worker/products")


def test_preview_fetch_keeps_bytes_in_memory(monkeypatch):
    captured = {}

    def fetch(path, *, preview_ref=""):
        captured.update(path=path, preview_ref=preview_ref)
        return b"png-bytes", "image/png"

    monkeypatch.setattr(access, "_gateway_request", fetch)
    ref = "workbench-image://rec_1/0/IMG-123"
    result = access.read_workbench_image_ref(ref)
    assert result == (b"png-bytes", "image/png")
    assert captured["path"] == "/api/opsboard/worker/images/rec_1/preview/0"
    assert captured["preview_ref"] == ref

