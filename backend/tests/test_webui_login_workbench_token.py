"""1.4.18 account sync: ``POST /api/webui/login-workbench-token`` + claim step 2.5.

Covers:
* ``workbench_me`` upstream contract — GET /api/auth/me with Bearer header;
  401/403 → 401 (工作台登录已失效), timeout / connect failure → 503,
  unexpected status / body without username → 502.
* Endpoint contract — 200 mints a shell WebUI JWT (auth_method=workbench,
  principal_id from ``ensure_workbench_principal``); WorkbenchAuthError
  passes through; empty / whitespace token → 400; deactivated → 403.
* ``/login-workbench`` echoes ``workbench_token`` (1.4.18); ``/login`` does NOT.
* Resolution step 2.5 — the org's FIRST workbench admin claims the local
  free-login (local-admin) principal: identity row bound, principal_id and
  display_name storage unchanged, attrs merge ``workbench_username``;
  second admin / member / post-existing-identity / deactivated candidate
  never claim. ``me_payload`` shows the workbench username for JWT sessions.
* Security — the workbench token (and password) never appear in logs.

The webui router module is loaded directly by file path via ``importlib``
to bypass ``app.gateway.routers.__init__`` (same isolation trick as
``test_webui_login_workbench.py``).

Run: cd backend && python -m pytest tests/test_webui_login_workbench_token.py -v
"""

from __future__ import annotations

import importlib.util
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_WEBUI_PATH = _BACKEND_ROOT / "app" / "gateway" / "routers" / "webui.py"

_WB_TOKEN = "wb-token-secret-should-not-log"
_WB_ME_OK = {"username": "jennifer", "role": "admin"}


def _load_webui_module():
    spec = importlib.util.spec_from_file_location("webui_wb_token_login", _WEBUI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["webui_wb_token_login"] = module
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


def _mock_workbench_me(monkeypatch: pytest.MonkeyPatch, me: dict[str, Any] | None, error: Exception | None = None) -> None:
    async def fake_me(token: str) -> dict[str, Any]:
        assert token, "workbench_me must receive the token"
        if error is not None:
            raise error
        assert me is not None
        return me

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_me", fake_me)


# ── workbench_me: upstream proxy contract (fake httpx GET) ──


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
    last_method: str | None = None
    last_headers: dict[str, str] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def _call(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        type(self).last_url = url
        type(self).last_method = method
        type(self).last_headers = dict(kwargs.get("headers") or {})
        if type(self).exc is not None:
            raise type(self).exc
        assert type(self).response is not None
        return type(self).response

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return await self._call("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return await self._call("POST", url, **kwargs)


@pytest.fixture()
def fake_httpx(monkeypatch: pytest.MonkeyPatch):
    _FakeAsyncClient.response = None
    _FakeAsyncClient.exc = None
    _FakeAsyncClient.last_url = None
    _FakeAsyncClient.last_method = None
    _FakeAsyncClient.last_headers = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_workbench_me_ok_parses_identity(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import workbench_me

    fake_httpx.response = _FakeResponse(200, {"username": "jennifer", "role": "Admin"})
    me = await workbench_me(_WB_TOKEN)
    assert me == {"username": "jennifer", "role": "admin"}
    assert fake_httpx.last_url == "https://workbench.kll666.cn/api/auth/me"
    assert fake_httpx.last_headers.get("Authorization") == f"Bearer {_WB_TOKEN}"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_workbench_me_rejected_maps_401_chinese(fake_httpx, status) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_me

    fake_httpx.response = _FakeResponse(status, {"detail": "x"})
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_me(_WB_TOKEN)
    assert ei.value.status_code == 401
    assert "工作台登录已失效，请在工作台重新登录" in ei.value.detail


@pytest.mark.asyncio
async def test_workbench_me_timeout_maps_503(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_me

    fake_httpx.exc = httpx.TimeoutException("boom")
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_me(_WB_TOKEN)
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_workbench_me_connect_error_maps_503(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_me

    fake_httpx.exc = httpx.ConnectError("refused")
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_me(_WB_TOKEN)
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_workbench_me_upstream_500_maps_502(fake_httpx) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_me

    fake_httpx.response = _FakeResponse(500, {"detail": "x"})
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_me(_WB_TOKEN)
    assert ei.value.status_code == 502


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resp",
    [
        _FakeResponse(200, {"role": "admin"}),  # missing username
        _FakeResponse(200, {"username": "   "}),  # blank username
        _FakeResponse(200, ["not", "a", "dict"]),
        _FakeResponse(200, None, json_error=True),  # non-JSON body
    ],
)
async def test_workbench_me_malformed_body_maps_502(fake_httpx, resp) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError, workbench_me

    fake_httpx.response = resp
    with pytest.raises(WorkbenchAuthError) as ei:
        await workbench_me(_WB_TOKEN)
    assert ei.value.status_code == 502


# ── Endpoint: POST /api/webui/login-workbench-token ──────────


def test_token_endpoint_200_mints_shell_jwt(client, patched_mints, monkeypatch) -> None:
    _mock_workbench_me(monkeypatch, _WB_ME_OK)
    resp = client.post("/api/webui/login-workbench-token", json={"workbench_token": _WB_TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "jennifer"
    assert data["token"] == "jwt:workbench:pid-jennifer:jennifer"
    assert patched_mints == [{"username": "jennifer", "role": "admin"}]
    # The shell JWT response never echoes the workbench token.
    assert "workbench_token" not in data
    assert _WB_TOKEN not in resp.text


def test_token_endpoint_member_role_passed_through(client, patched_mints, monkeypatch) -> None:
    _mock_workbench_me(monkeypatch, {"username": "bob", "role": "member"})
    resp = client.post("/api/webui/login-workbench-token", json={"workbench_token": _WB_TOKEN})
    assert resp.status_code == 200
    assert patched_mints == [{"username": "bob", "role": "member"}]


@pytest.mark.parametrize("token", ["", "   "])
def test_token_endpoint_blank_token_400(client, patched_mints, monkeypatch, token) -> None:
    _mock_workbench_me(monkeypatch, _WB_ME_OK)
    resp = client.post("/api/webui/login-workbench-token", json={"workbench_token": token})
    assert resp.status_code == 400
    assert patched_mints == []


def test_token_endpoint_missing_field_422(client, patched_mints) -> None:
    resp = client.post("/api/webui/login-workbench-token", json={})
    assert resp.status_code == 422
    assert patched_mints == []


def test_token_endpoint_workbench_401_maps_401(client, patched_mints, monkeypatch) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError

    async def fake_me(token: str):
        raise WorkbenchAuthError(401, "工作台登录已失效，请在工作台重新登录")

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_me", fake_me)
    resp = client.post("/api/webui/login-workbench-token", json={"workbench_token": _WB_TOKEN})
    assert resp.status_code == 401
    assert "工作台登录已失效" in resp.json()["detail"]
    assert patched_mints == []


def test_token_endpoint_workbench_timeout_maps_503(client, patched_mints, monkeypatch) -> None:
    from evoflow.webui.workbench_auth import WorkbenchAuthError

    async def fake_me(token: str):
        raise WorkbenchAuthError(503, "工作台登录服务暂不可用（超时），请稍后重试")

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_me", fake_me)
    resp = client.post("/api/webui/login-workbench-token", json={"workbench_token": _WB_TOKEN})
    assert resp.status_code == 503
    assert patched_mints == []


def test_token_endpoint_deactivated_principal_403(client, patched_mints, monkeypatch) -> None:
    _mock_workbench_me(monkeypatch, _WB_ME_OK)

    def fake_ensure(*, username, role=None, **kwargs):
        raise ValueError("principal is deactivated")

    monkeypatch.setattr("evoflow.authz.principals.ensure_workbench_principal", fake_ensure)
    resp = client.post("/api/webui/login-workbench-token", json={"workbench_token": _WB_TOKEN})
    assert resp.status_code == 403
    assert "已停用" in resp.json()["detail"] or "deactivated" in resp.json()["detail"]


# ── workbench_token echo: login-workbench vs login ───────────


def test_login_workbench_echoes_workbench_token(client, patched_mints, monkeypatch) -> None:
    async def fake_login(username: str, password: str):
        return {"token": _WB_TOKEN, "username": username, "role": "admin"}

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_login", fake_login)
    resp = client.post("/api/webui/login-workbench", json={"username": "alice", "password": "pw"})
    assert resp.status_code == 200
    assert resp.json()["workbench_token"] == _WB_TOKEN


def test_plain_login_never_echoes_workbench_token(webui_module, monkeypatch) -> None:
    monkeypatch.setattr(
        webui_module,
        "verify_user_credentials",
        lambda u, p: {"id": 1, "username": u},
    )
    monkeypatch.setattr(webui_module, "get_webui_secret", lambda: "test-secret")
    monkeypatch.setattr(webui_module, "generate_jwt", _fake_jwt)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(webui_module.router)
    with TestClient(app) as tc:
        resp = tc.post("/api/webui/login", json={"username": "admin", "password": "pw"})
    assert resp.status_code == 200
    assert "workbench_token" not in resp.json()


# ── Resolution step 2.5: first workbench admin claims local-admin ──


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


@pytest.fixture()
def jwt_capture(webui_module, monkeypatch: pytest.MonkeyPatch):
    """Real ensure_workbench_principal; deterministic secret + captured JWT args."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(webui_module, "get_webui_secret", lambda: "test-secret")

    def fake_jwt(uid, username, secret, *, principal_id=None, auth_method="password"):
        captured.update(
            {"username": username, "principal_id": principal_id, "auth_method": auth_method}
        )
        return f"jwt:{auth_method}:{principal_id}:{username}"

    monkeypatch.setattr(webui_module, "generate_jwt", fake_jwt)
    return captured


def _post_token_login(client, monkeypatch, *, username: str, role: str) -> dict[str, Any]:
    _mock_workbench_me(monkeypatch, {"username": username, "role": role})
    resp = client.post("/api/webui/login-workbench-token", json={"workbench_token": _WB_TOKEN})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_first_workbench_admin_claims_local_admin(app_db, client, jwt_capture, monkeypatch) -> None:
    from evoflow.authz import principals as pm

    la = pm.get_or_create_local_admin()
    assert str(la["principal_id"]) == "local-admin"
    display_before = str(la["display_name"])

    data = _post_token_login(client, monkeypatch, username="jennifer", role="admin")

    # JWT carries the claimed principal_id — principal_id never changes.
    assert jwt_capture["principal_id"] == "local-admin"
    assert jwt_capture["auth_method"] == "workbench"
    assert data["username"] == "jennifer"
    # Identity row bound to local-admin; display_name storage untouched.
    assert pm.resolve_principal_by_identity("workbench", "jennifer")["principal_id"] == "local-admin"
    after = pm.get_principal("local-admin")
    assert str(after["display_name"]) == display_before
    assert after["attrs"].get("workbench_username") == "jennifer"
    # me_payload: JWT session shows the workbench username (context.py unchanged).
    from evoflow.authz.context import build_authz_context, me_payload

    ctx = build_authz_context(after)
    payload = me_payload(ctx, auth_source="jwt", username="jennifer")
    assert payload["principalId"] == "local-admin"
    assert payload["username"] == "jennifer"
    assert payload["displayName"] == "jennifer"
    assert payload["authSource"] == "jwt"


def test_second_workbench_admin_does_not_claim(app_db, client, jwt_capture, monkeypatch) -> None:
    from evoflow.authz import principals as pm

    pm.get_or_create_local_admin()
    _post_token_login(client, monkeypatch, username="jennifer", role="admin")
    data = _post_token_login(client, monkeypatch, username="kevin", role="admin")
    assert data["username"] == "kevin"
    assert jwt_capture["principal_id"] == "kevin"  # fresh principal, not local-admin
    assert pm.resolve_principal_by_identity("workbench", "kevin")["principal_id"] == "kevin"


def test_member_never_claims(app_db, client, jwt_capture, monkeypatch) -> None:
    from evoflow.authz import principals as pm

    pm.get_or_create_local_admin()
    _post_token_login(client, monkeypatch, username="bob", role="member")
    assert jwt_capture["principal_id"] == "bob"
    assert pm.resolve_principal_by_identity("workbench", "bob")["principal_id"] == "bob"


def test_no_claim_when_workbench_identity_already_exists(app_db, client, jwt_capture, monkeypatch) -> None:
    """Org already has a workbench identity (e.g. re-login after step 3)."""
    from evoflow.authz import principals as pm

    pm.ensure_workbench_principal(username="dave", role="member")  # creates the first identity
    pm.get_or_create_local_admin()
    _post_token_login(client, monkeypatch, username="erin", role="admin")
    assert jwt_capture["principal_id"] == "erin"
    assert pm.resolve_principal_by_identity("workbench", "erin")["principal_id"] == "erin"


def test_no_claim_when_local_admin_deactivated(app_db, client, jwt_capture, monkeypatch) -> None:
    from evoflow.authz import principals as pm

    la = pm.get_or_create_local_admin()
    assert pm.set_principal_status(str(la["principal_id"]), "deactivated")
    _post_token_login(client, monkeypatch, username="jennifer", role="admin")
    assert jwt_capture["principal_id"] == "jennifer"
    assert pm.resolve_principal_by_identity("workbench", "jennifer")["principal_id"] == "jennifer"


def test_claim_keeps_old_local_admin_sessions_reachable(app_db, client, jwt_capture, monkeypatch) -> None:
    """Assets/sessions created under local-admin resolve under the workbench principal."""
    from evoflow.authz import principals as pm

    la = pm.get_or_create_local_admin()
    # Identity linkage is what /apps & session lists resolve through.
    _post_token_login(client, monkeypatch, username="jennifer", role="admin")
    rows = app_db.execute(
        "SELECT principal_id FROM evoflow_principal_identities WHERE provider = 'workbench' AND external_id = 'jennifer'"
    ).fetchall()
    assert [r[0] for r in rows] == [str(la["principal_id"])]
    # No password row was ever created for the workbench identity.
    assert int(app_db.execute("SELECT COUNT(*) FROM evoflow_webui_users").fetchone()[0]) == 0


# ── Security: no secrets in logs ─────────────────────────────


def test_token_and_password_never_logged(app_db, client, jwt_capture, monkeypatch, caplog) -> None:
    async def fake_login(username: str, password: str):
        return {"token": _WB_TOKEN, "username": username, "role": "admin"}

    monkeypatch.setattr("evoflow.webui.workbench_auth.workbench_login", fake_login)
    caplog.set_level(logging.DEBUG)
    with caplog.at_level(logging.DEBUG):
        pm_post = client.post(
            "/api/webui/login-workbench",
            json={"username": "alice", "password": "super-secret-pw-xyz"},
        )
        assert pm_post.status_code == 200
        _mock_workbench_me(monkeypatch, _WB_ME_OK)
        tk = client.post("/api/webui/login-workbench-token", json={"workbench_token": _WB_TOKEN})
        assert tk.status_code == 200
    assert _WB_TOKEN not in caplog.text
    assert "super-secret-pw-xyz" not in caplog.text
