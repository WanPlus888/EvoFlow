"""Shell login unification 方案1 (1.4.15): ``POST /api/webui/login-workbench``.

Covers:
* Upstream proxy contract — workbench 401 → 401 (Chinese detail), timeout /
  connect failure → 503, unexpected status / malformed body → 502.
* Endpoint contract — 200 mints a shell WebUI JWT (auth_method=workbench,
  principal_id from ``ensure_workbench_principal``); workbench 401/502/503
  pass through; malformed params → 400; the workbench token is never echoed.
* Principal mapping — JIT provision (no local password row), idempotency,
  same-username local-user linking, role admin → org admin, deactivated
  rejection, and that the old ``evoflow_webui_users`` password check is NOT
  involved in the workbench path.

The webui router module is loaded directly by file path via ``importlib``
to bypass ``app.gateway.routers.__init__`` (same isolation trick as
``test_webui_login.py``).

Run: cd backend && python -m pytest tests/test_webui_login_workbench.py -v
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_WEBUI_PATH = _BACKEND_ROOT / "app" / "gateway" / "routers" / "webui.py"

_WB_OK_BODY = {"token": "wb-token-should-not-escape", "username": "alice", "role": "admin"}


# ── Load webui router by file path (bypass routers/__init__) ─


def _load_webui_module():
    spec = importlib.util.spec_from_file_location("webui_wb_login_regression", _WEBUI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["webui_wb_login_regression"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def webui_module():
    return _load_webui_module()


@pytest.fixture()
def client(webui_module):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(webui_module.router)
    return TestClient(app)


def _fake_jwt(uid: Any, username: str, secret: str, *, principal_id: str | None = None, auth_method: str = "password") -> str:
    return f"jwt:{auth_method}:{principal_id}:{username}"


@pytest.fixture()
def patched_mints(webui_module, monkeypatch: pytest.MonkeyPatch):
    """Deterministic secret/JWT + capture ensure_workbench_principal calls."""
    calls: list[dict[str, Any]] = []

    def fake_ensure(*, username: str, role: str | None = None, **kwargs: Any) -> dict[str, Any]:
        calls.append({"username": username, "role": role})
        return {"principal_id": f"pid-{username}"}

    monkeypatch.setattr(webui_module, "get_webui_secret", lambda: "test-secret")
    monkeypatch.setattr(webui_module, "generate_jwt", _fake_jwt)
    monkeypatch.setattr("evoflow.authz.principals.ensure_workbench_principal", fake_ensure)
    return calls


def _mock_workbench(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any] | None, error: Exception | None = None) -> None:
    async def fake_login(username: str, password: str) -> dict[str, Any]:
        if error is not None:
            raise error
        assert payload is not None
        return payload

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_login", fake_login)


# ── workbench_login: upstream proxy contract ────────────────


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, json_error: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error:
            raise ValueError("not json")
        return self._payload


class _FakeAsyncClient:
    response: _FakeResponse | None = None
    exc: Exception | None = None
    last_url: str | None = None
    last_json: dict[str, Any] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        type(self).last_url = url
        type(self).last_json = json
        if type(self).exc is not None:
            raise type(self).exc
        assert type(self).response is not None
        return type(self).response


@pytest.fixture()
def fake_httpx(monkeypatch: pytest.MonkeyPatch):
    _FakeAsyncClient.response = None
    _FakeAsyncClient.exc = None
    _FakeAsyncClient.last_url = None
    _FakeAsyncClient.last_json = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_workbench_login_ok_parses_body(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import workbench_login

    fake_httpx.response = _FakeResponse(200, {"token": "tok", "username": "alice", "role": "admin"})
    body = await workbench_login("alice", "pw")
    assert body["token"] == "tok"
    assert fake_httpx.last_url == "https://workbench.kll666.cn/api/auth/login"
    assert fake_httpx.last_json == {"username": "alice", "password": "pw"}


@pytest.mark.asyncio
async def test_workbench_login_401_passes_chinese_detail(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_login

    fake_httpx.response = _FakeResponse(401, {"detail": "用户名或密码不对"})
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_login("alice", "bad")
    assert ei.value.status_code == 401
    assert "用户名或密码不对" in ei.value.detail


@pytest.mark.asyncio
async def test_workbench_login_timeout_maps_503(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_login

    fake_httpx.exc = httpx.TimeoutException("boom")
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_login("alice", "pw")
    assert ei.value.status_code == 503
    assert "工作台登录服务暂不可用" in ei.value.detail


@pytest.mark.asyncio
async def test_workbench_login_connect_error_maps_503(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_login

    fake_httpx.exc = httpx.ConnectError("refused")
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_login("alice", "pw")
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_workbench_login_upstream_500_maps_502(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_login

    fake_httpx.response = _FakeResponse(500, {"detail": "x"})
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_login("alice", "pw")
    assert ei.value.status_code == 502


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resp",
    [
        _FakeResponse(200, {"username": "alice"}),  # missing token
        _FakeResponse(200, ["not", "a", "dict"]),
        _FakeResponse(200, None, json_error=True),  # non-JSON body
    ],
)
async def test_workbench_login_malformed_success_maps_502(fake_httpx, resp) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_login

    fake_httpx.response = resp
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_login("alice", "pw")
    assert ei.value.status_code == 502


def test_workbench_auth_base_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from evoflow.webui.workbench_auth import WORKBENCH_AUTH_BASE_DEFAULT, get_workbench_auth_base

    assert get_workbench_auth_base() == WORKBENCH_AUTH_BASE_DEFAULT == "https://workbench.kll666.cn"
    monkeypatch.setenv("EVOFLOW_WORKBENCH_AUTH_BASE", "https://wb.example.com/")
    assert get_workbench_auth_base() == "https://wb.example.com"


# ── Endpoint: POST /api/webui/login-workbench ────────────────


def test_endpoint_200_mints_shell_jwt(client, patched_mints, monkeypatch) -> None:
    _mock_workbench(monkeypatch, _WB_OK_BODY)
    resp = client.post("/api/webui/login-workbench", json={"username": "alice", "password": "pw"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "alice"
    # Shell JWT minted via the gateway's own signer, auth_method=workbench.
    assert data["token"] == "jwt:workbench:pid-alice:alice"
    # The workbench token must never be echoed to the shell client.
    assert "wb-token-should-not-escape" not in resp.text
    assert patched_mints == [{"username": "alice", "role": "admin"}]


def test_endpoint_falls_back_to_submitted_username(client, patched_mints, monkeypatch) -> None:
    _mock_workbench(monkeypatch, {"token": "wb-tok", "role": "member"})
    resp = client.post("/api/webui/login-workbench", json={"username": "bob", "password": "pw"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "bob"
    assert patched_mints == [{"username": "bob", "role": "member"}]


def test_endpoint_workbench_401_maps_401_chinese(client, patched_mints, monkeypatch) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError

    async def fake_login(username, password):
        raise WorkbenchAuthError(401, "用户名或密码不对")

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_login", fake_login)
    resp = client.post("/api/webui/login-workbench", json={"username": "alice", "password": "bad"})
    assert resp.status_code == 401
    assert "用户名或密码不对" in resp.json()["detail"]
    assert patched_mints == []  # no principal minted on failure


def test_endpoint_workbench_unavailable_maps_503_no_jwt(client, patched_mints, monkeypatch) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError

    async def fake_login(username, password):
        raise WorkbenchAuthError(503, "工作台登录服务暂不可用（超时），请稍后重试")

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_login", fake_login)
    resp = client.post("/api/webui/login-workbench", json={"username": "alice", "password": "pw"})
    assert resp.status_code == 503
    assert "工作台登录服务暂不可用" in resp.json()["detail"]
    assert patched_mints == []


def test_endpoint_empty_params_400(client, patched_mints, monkeypatch) -> None:
    _mock_workbench(monkeypatch, _WB_OK_BODY)
    resp = client.post("/api/webui/login-workbench", json={"username": "  ", "password": "pw"})
    assert resp.status_code == 400
    assert patched_mints == []


def test_endpoint_deactivated_principal_403(client, patched_mints, monkeypatch) -> None:
    async def fake_login(username, password):
        return _WB_OK_BODY

    def fake_ensure(*, username, role=None, **kwargs):
        raise ValueError("principal is deactivated")

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_login", fake_login)
    monkeypatch.setattr("evoflow.authz.principals.ensure_workbench_principal", fake_ensure)
    resp = client.post("/api/webui/login-workbench", json={"username": "alice", "password": "pw"})
    assert resp.status_code == 403


# ── ensure_workbench_principal: DB-backed mapping ────────────


@pytest.fixture()
def app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Throwaway app DB with fully-migrated schema (same as identity tests)."""
    from evoflow.persistence import db as db_mod

    db_path = tmp_path / "evoflow.db"
    monkeypatch.setenv("EVOFLOW_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_cached_default_path", db_path, raising=False)
    monkeypatch.setattr(db_mod, "_DB_SINGLETON", None, raising=False)
    monkeypatch.setattr(db_mod, "_db_singleton", None, raising=False)
    conn = db_mod.get_db()
    yield conn
    try:
        db_mod.close_db()
    except Exception:
        pass


def _webui_user_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM evoflow_webui_users").fetchone()[0])


def test_ensure_provisions_passwordless_principal(app_db) -> None:
    from evoflow.authz import principals as pm

    p = pm.ensure_workbench_principal(username="alice", role="member")
    assert p["principal_id"] == "alice"
    assert p["display_name"] == "alice"
    assert p["attrs"].get("auth_method") == "workbench"
    assert p["attrs"].get("workbench_role") == "member"
    # Identity row exists under the workbench provider.
    assert pm.resolve_principal_by_identity("workbench", "alice")["principal_id"] == "alice"
    # Password-free mapping: no evoflow_webui_users row is created.
    assert _webui_user_count(app_db) == 0


def test_ensure_is_idempotent(app_db) -> None:
    from evoflow.authz import principals as pm

    p1 = pm.ensure_workbench_principal(username="alice", role="member")
    p2 = pm.ensure_workbench_principal(username="alice", role="member")
    assert p1["principal_id"] == p2["principal_id"] == "alice"
    rows = app_db.execute(
        "SELECT COUNT(*) FROM evoflow_principal_identities WHERE provider = 'workbench' AND external_id = 'alice'"
    ).fetchone()[0]
    assert int(rows) == 1


def test_ensure_links_existing_local_user_same_username(app_db) -> None:
    from evoflow.authz import principals as pm

    local = pm.ensure_webui_principal(webui_user_id=7, username="bob", is_primary=False)
    before = _webui_user_count(app_db)
    p = pm.ensure_workbench_principal(username="bob", role="member")
    # One username = one person = one principal; no new local user row.
    assert p["principal_id"] == local["principal_id"]
    assert _webui_user_count(app_db) == before
    assert pm.resolve_principal_by_identity("workbench", "bob")["principal_id"] == local["principal_id"]


def test_ensure_role_admin_promotes_org_admin(app_db) -> None:
    from evoflow.authz import admin_grants
    from evoflow.authz import principals as pm

    p = pm.ensure_workbench_principal(username="carol", role="admin")
    assert admin_grants.is_org_admin(str(p["principal_id"]))
    # member must NOT be promoted
    m = pm.ensure_workbench_principal(username="dave", role="member")
    assert not admin_grants.is_org_admin(str(m["principal_id"]))


def test_ensure_rejects_deactivated(app_db) -> None:
    from evoflow.authz import principals as pm

    p = pm.ensure_workbench_principal(username="erin", role="member")
    assert pm.set_principal_status(str(p["principal_id"]), "deactivated")
    with pytest.raises(ValueError):
        pm.ensure_workbench_principal(username="erin", role="member")


def test_ensure_requires_username(app_db) -> None:
    from evoflow.authz import principals as pm

    with pytest.raises(ValueError):
        pm.ensure_workbench_principal(username="   ")


def test_workbench_path_does_not_touch_local_password_check(app_db, monkeypatch) -> None:
    """The unified path must not verify against evoflow_webui_users hashes."""
    def _fail(*args: Any, **kwargs: Any):
        raise AssertionError("verify_user_credentials must not run on the workbench path")

    _mock_workbench(monkeypatch, _WB_OK_BODY)
    webui_mod = _load_webui_module()
    # Patch the binding the router actually calls (module-local name).
    monkeypatch.setattr(webui_mod, "verify_user_credentials", _fail)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(webui_mod.router)
    with TestClient(app) as tc:
        resp = tc.post("/api/webui/login-workbench", json={"username": "alice", "password": "irrelevant-local-pw"})
    assert resp.status_code == 200
