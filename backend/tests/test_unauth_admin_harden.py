"""1.4.20 网关公网无鉴权硬化回归（gw-unauth-harden 刀 B）。

覆盖（对应 zcode-tasks/20261109-gw-unauth-harden-steps.md S6）：
* 信任边界助手 —— ``_forwarded_client_hosts`` / ``_is_ip_loopback`` /
  ``is_unauth_admin_bootstrap_allowed``（X-Forwarded-For / X-Real-IP / 环境变量）。
* ``require_org_admin`` / ``require_authenticated`` —— 无信号且非真本机 bootstrap → 401；
  有信号非 admin → 403；本机 loopback 无转发头保持单用户 bootstrap。
* ``resolve_request_authz`` —— 公网无凭据请求 principal 仍回落 local-admin 但
  ``is_org_admin`` 被剥（垃圾 cookie/Bearer 同样剥）。
* API 面 —— DELETE /api/agents/{main}、POST /api/models、POST /api/agents、
  PUT /api/agents/main、promote-admin 无鉴权 + X-Forwarded-For → 401/403；
  GET /api/identity/me → isOrgAdmin=false；本机直连 → isOrgAdmin=true；
  带 admin principal 头 → 管理功能正常（AC4）。
* 安全 —— 响应/日志不含 token 字面值。

Run: cd backend && .venv/bin/python -m pytest tests/test_unauth_admin_harden.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from evoflow.authz.http_guard import (
    _forwarded_client_hosts,
    _is_ip_loopback,
    is_unauth_admin_bootstrap_allowed,
    require_authenticated,
    require_org_admin,
)

PUBLIC_IP = "203.0.113.10"
XFF_PUBLIC = {"x-forwarded-for": PUBLIC_IP}
XRI_PUBLIC = {"x-real-ip": PUBLIC_IP}


def make_request(
    *,
    client_host: str = "127.0.0.1",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    path: str = "/api/identity/me",
) -> Request:
    """手工构造 starlette Request，完全掌控 client.host / headers / cookies。"""
    hdrs = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    if cookies:
        hdrs["cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.encode(), v.encode()) for k, v in hdrs.items()],
        "client": (client_host, 52341),
        "server": ("127.0.0.1", 8012),
    }
    req = Request(scope)
    if getattr(req.state, "webui_user", None) is None:
        req.state.webui_user = None  # 显式占位，模拟「无有效 JWT」
    return req


@pytest.fixture()
def app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Throwaway app DB + data dir（同 test_webui_login_workbench_token 口径）。"""
    from evoflow.config import paths as paths_mod
    from evoflow.persistence import db as db_mod

    db_path = tmp_path / "evoflow.db"
    monkeypatch.setenv("EVOFLOW_DB_PATH", str(db_path))
    monkeypatch.setenv("EVOFLOW_HOME", str(tmp_path / "evoflow-home"))
    monkeypatch.setattr(paths_mod, "_paths", None, raising=False)
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
def api(app_db):
    """真路由（agents/models/identity）挂裸 FastAPI；client 固定 loopback，
    公网形态用 X-Forwarded-For 头模拟 nginx 反代。"""
    from app.gateway.routers import agents as agents_router
    from app.gateway.routers import identity as identity_router
    from app.gateway.routers import models as models_router

    app = FastAPI()
    app.include_router(agents_router.router)
    app.include_router(models_router.router)
    app.include_router(identity_router.router)
    return TestClient(app, client=("127.0.0.1", 52341))


def _seed_admin_principal(pid: str = "pid-admin-harden") -> str:
    from evoflow.authz import admin_grants, principals

    p = principals.create_principal(display_name=pid, principal_id=pid)
    admin_grants.promote_org_admin(str(p["principal_id"]), granted_by=None)
    return str(p["principal_id"])


def _seed_member_principal(pid: str = "pid-member-harden") -> str:
    from evoflow.authz import principals

    p = principals.create_principal(display_name=pid, principal_id=pid)
    return str(p["principal_id"])


# ── 信任边界助手（纯函数，无 DB）──


def test_forwarded_client_hosts_parses_xff_and_real_ip_in_order():
    req = make_request(headers={"x-forwarded-for": "203.0.113.10, 198.51.100.7", "x-real-ip": "192.0.2.9"})
    assert _forwarded_client_hosts(req) == ["203.0.113.10", "198.51.100.7", "192.0.2.9"]


def test_forwarded_client_hosts_empty_without_headers():
    assert _forwarded_client_hosts(make_request()) == []


def test_forwarded_client_hosts_none_request_returns_empty():
    assert _forwarded_client_hosts(None) == []


def test_forwarded_client_hosts_ignores_blank_segments():
    req = make_request(headers={"x-forwarded-for": " , 127.0.0.1 , "})
    assert _forwarded_client_hosts(req) == ["127.0.0.1"]


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("127.0.0.9", True),  # 127/8 全段是本机
        ("::1", True),
        ("[::1]", True),
        ("LOCALHOST", True),
        (PUBLIC_IP, False),
        ("198.51.100.7", False),
        ("not-an-ip", False),
        ("", False),
    ],
)
def test_is_ip_loopback_variants(host: str, expected: bool):
    assert _is_ip_loopback(host) is expected


# ── is_unauth_admin_bootstrap_allowed（纯函数，无 DB）──


def test_bootstrap_allowed_for_pure_loopback_no_forward_headers():
    assert is_unauth_admin_bootstrap_allowed(make_request()) is True


def test_bootstrap_denied_when_any_forwarded_public_ip():
    assert is_unauth_admin_bootstrap_allowed(make_request(headers=XFF_PUBLIC)) is False


def test_bootstrap_denied_when_x_real_ip_public():
    assert is_unauth_admin_bootstrap_allowed(make_request(headers=XRI_PUBLIC)) is False


def test_bootstrap_allowed_when_all_forwarded_loopback():
    req = make_request(headers={"x-forwarded-for": "127.0.0.1, ::1", "x-real-ip": "127.0.0.1"})
    assert is_unauth_admin_bootstrap_allowed(req) is True


def test_bootstrap_denied_for_none_request():
    assert is_unauth_admin_bootstrap_allowed(None) is False


def test_bootstrap_denied_when_direct_client_not_loopback():
    assert is_unauth_admin_bootstrap_allowed(make_request(client_host=PUBLIC_IP)) is False


def test_bootstrap_denied_when_client_missing():
    req = make_request()
    req.scope["client"] = None
    assert is_unauth_admin_bootstrap_allowed(req) is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "On"])
def test_bootstrap_denied_env_disable_variants(value: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLOW_DISABLE_UNAUTH_ADMIN", value)
    assert is_unauth_admin_bootstrap_allowed(make_request()) is False


@pytest.mark.parametrize("value", ["0", "", "off"])
def test_bootstrap_env_falsy_values_keep_bootstrap(value: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLOW_DISABLE_UNAUTH_ADMIN", value)
    assert is_unauth_admin_bootstrap_allowed(make_request()) is True


# ── require_org_admin / require_authenticated（守卫单元）──


def test_require_org_admin_unauth_proxied_401_not_403():
    with pytest.raises(HTTPException) as ei:
        require_org_admin(make_request(headers=XFF_PUBLIC))
    assert ei.value.status_code == 401


def test_require_org_admin_bootstrap_loopback_passes():
    require_org_admin(make_request())  # 不抛即通过


def test_require_org_admin_env_disable_401(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLOW_DISABLE_UNAUTH_ADMIN", "1")
    with pytest.raises(HTTPException) as ei:
        require_org_admin(make_request())
    assert ei.value.status_code == 401


def test_require_org_admin_pid_header_admin_passes(app_db):
    pid = _seed_admin_principal()
    require_org_admin(make_request(headers={"x-evoflow-principal-id": pid}))  # 不抛


def test_require_org_admin_pid_header_non_admin_403(app_db):
    pid = _seed_member_principal()
    with pytest.raises(HTTPException) as ei:
        require_org_admin(make_request(headers={"x-evoflow-principal-id": pid}))
    assert ei.value.status_code == 403


def test_require_org_admin_garbage_bearer_proxied_403(app_db):
    """垃圾 Bearer 头是「有信号」但解析不出身份 → 非 admin → 403（不得放行）。"""
    with pytest.raises(HTTPException) as ei:
        require_org_admin(make_request(headers={"authorization": "Bearer garbage", **XFF_PUBLIC}))
    assert ei.value.status_code == 403


def test_require_org_admin_valid_webui_user_admin_passes(app_db):
    pid = _seed_admin_principal()
    req = make_request()
    req.state.webui_user = {"principal_id": pid, "username": "admin-x"}
    require_org_admin(req)  # 不抛


def test_require_authenticated_unauth_proxied_401():
    with pytest.raises(HTTPException) as ei:
        require_authenticated(make_request(headers=XFF_PUBLIC))
    assert ei.value.status_code == 401


def test_require_authenticated_bootstrap_passes():
    require_authenticated(make_request())  # 不抛


def test_require_authenticated_any_signal_passes_gate():
    require_authenticated(make_request(headers={"authorization": "Bearer garbage"}))  # 不抛（后续 ownership 兜）


# ── resolve_request_authz：isOrgAdmin 口径 ──


def test_resolve_authz_bootstrap_is_org_admin_true(app_db):
    from evoflow.authz.context import resolve_request_authz

    ctx = resolve_request_authz(make_request())
    assert ctx.get("is_org_admin") is True


def test_resolve_authz_proxied_unauth_strips_admin_keeps_local_admin(app_db):
    from evoflow.authz.context import resolve_request_authz
    from evoflow.authz.principals import LOCAL_ADMIN_PRINCIPAL_ID

    ctx = resolve_request_authz(make_request(headers=XFF_PUBLIC))
    # local-admin 回落保留（读 /me 兼容），但管理权被剥
    assert str((ctx.get("principal") or {}).get("principal_id") or "") == LOCAL_ADMIN_PRINCIPAL_ID
    assert ctx.get("is_org_admin") is False


def test_resolve_authz_garbage_cookie_proxied_strips_admin(app_db):
    from evoflow.authz.context import resolve_request_authz

    req = make_request(headers=XFF_PUBLIC, cookies={"evoflow_webui_token": "garbage-cookie"})
    assert resolve_request_authz(req).get("is_org_admin") is False


def test_resolve_authz_pid_header_admin_keeps_admin(app_db):
    from evoflow.authz.context import resolve_request_authz

    pid = _seed_admin_principal()
    ctx = resolve_request_authz(make_request(headers={"x-evoflow-principal-id": pid}))
    assert ctx.get("is_org_admin") is True


def test_resolve_authz_none_request_keeps_admin(app_db):
    """非 HTTP 调用方（后台任务）不受本刀影响。"""
    from evoflow.authz.context import resolve_request_authz

    assert resolve_request_authz(None).get("is_org_admin") is True


# ── API 面：公网无鉴权 → 401/403（不得 204/422/200 管理数据）──


def test_api_delete_agents_main_proxied_unauth_401_not_204(api: TestClient):
    resp = api.delete("/api/agents/main", headers=XFF_PUBLIC)
    assert resp.status_code == 401
    assert resp.status_code != 204  # 审计 2026-11-09 曾无 JWT 删 main → 204


def test_api_delete_agents_custom_proxied_unauth_401(api: TestClient):
    resp = api.delete("/api/agents/someone-agent", headers=XFF_PUBLIC)
    assert resp.status_code == 401


def test_api_delete_agents_bootstrap_passes_gate_then_404_missing(api: TestClient):
    """AC3：本机直连 bootstrap 仍过 admin 门（404 = 门过了、agent 不存在）。"""
    resp = api.delete("/api/agents/no-such-agent-harden")
    assert resp.status_code == 404


def test_api_post_models_proxied_unauth_401_not_422(api: TestClient):
    """合法 body 才能到达守卫；审计曾空 body 即 422（已过 admin 门）。"""
    resp = api.post(
        "/api/models",
        json={"name": "harden-probe-model", "model": "test-model-id"},
        headers=XFF_PUBLIC,
    )
    assert resp.status_code == 401
    assert resp.status_code != 422


def test_api_post_agents_proxied_unauth_401(api: TestClient):
    resp = api.post(
        "/api/agents",
        json={"agent_code": "harden-probe-agent", "agent_name": "Harden Probe"},
        headers=XFF_PUBLIC,
    )
    assert resp.status_code == 401


def test_api_put_agents_main_proxied_unauth_401(api: TestClient):
    resp = api.put("/api/agents/main", json={"description": "pwn"}, headers=XFF_PUBLIC)
    assert resp.status_code == 401


def test_api_promote_admin_proxied_unauth_401(api: TestClient):
    resp = api.post("/api/identity/principals/someone/promote-admin", headers=XFF_PUBLIC)
    assert resp.status_code == 401


def test_api_principals_list_proxied_unauth_401_bootstrap_200(api: TestClient):
    assert api.get("/api/identity/principals", headers=XFF_PUBLIC).status_code == 401
    assert api.get("/api/identity/principals").status_code == 200


# ── API 面：/me isOrgAdmin 口径（AC1 / AC3 / AC4）──


def test_api_me_proxied_unauth_isorgadmin_false(api: TestClient):
    resp = api.get("/api/identity/me", headers=XFF_PUBLIC)
    assert resp.status_code == 200
    assert resp.json().get("isOrgAdmin") is False


def test_api_me_bootstrap_isorgadmin_true(api: TestClient):
    resp = api.get("/api/identity/me")
    assert resp.status_code == 200
    assert resp.json().get("isOrgAdmin") is True


def test_api_me_garbage_bearer_proxied_isorgadmin_false(api: TestClient):
    resp = api.get("/api/identity/me", headers={"authorization": "Bearer garbage", **XFF_PUBLIC})
    assert resp.status_code == 200
    assert resp.json().get("isOrgAdmin") is False


def test_api_me_pid_header_admin_isorgadmin_true(api: TestClient, app_db):
    pid = _seed_admin_principal()
    resp = api.get("/api/identity/me", headers={"x-evoflow-principal-id": pid})
    assert resp.status_code == 200
    assert resp.json().get("isOrgAdmin") is True


def test_api_me_env_disable_isorgadmin_false(api: TestClient, monkeypatch: pytest.MonkeyPatch):
    """AC5：即便反代漏转发头，env 也兜底关掉无鉴权 admin。"""
    monkeypatch.setenv("EVOFLOW_DISABLE_UNAUTH_ADMIN", "1")
    resp = api.get("/api/identity/me")
    assert resp.status_code == 200
    assert resp.json().get("isOrgAdmin") is False


# ── 安全：token 字面值不外泄 ──


def test_no_token_literal_in_responses(api: TestClient):
    sentinel = "SECRET-EVOTOKEN-DO-NOT-LEAK"
    resp = api.get(
        "/api/identity/me",
        headers={"authorization": f"Bearer {sentinel}", "x-evoflow-principal-id": "pid-no-such", **XFF_PUBLIC},
    )
    body = resp.text
    assert sentinel not in body
    assert "SECRET-EVOTOKEN" not in body
