"""AI 工作台 (workbench) credential proxy for shell login unification (方案1).

The shell's switch-user login authenticates against the workbench
``POST /api/auth/login`` (default ``https://workbench.kll666.cn``). The
workbench stays the **sole** credential source — no workbench password is
ever persisted locally. The gateway proxies the call server-side (no browser
CORS; base URL stays in server config), maps the workbench username to a
shell principal and mints the normal WebUI JWT.

1.4.18 (account sync): ``workbench_me`` verifies an already-issued workbench
``token`` (the iframe SSO shim captures it from the workbench page) via
``GET /api/auth/me``, so the shell can follow the workbench login without
ever seeing a password. The ``/login-workbench`` route may hand the workbench
``token`` back to the shell *client* on purpose (one-time passthrough, never
persisted server-side) so the shell can seed the workbench iframe login.
Tokens are never logged.
"""

from __future__ import annotations

import os
from typing import Any

WORKBENCH_AUTH_BASE_DEFAULT = "https://workbench.kll666.cn"

# Hard cap for the upstream login call (steps 1.4.15 §4.1: 超时 ≤10s).
WORKBENCH_LOGIN_TIMEOUT_S = 10.0


class WorkbenchAuthError(Exception):
    """Upstream workbench login failure mapped to an HTTP-friendly error."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = str(detail)


def get_workbench_auth_base() -> str:
    """Resolve the workbench auth base URL (env override, no trailing slash)."""
    base = (os.environ.get("EVOFLOW_WORKBENCH_AUTH_BASE", "") or "").strip()
    return (base or WORKBENCH_AUTH_BASE_DEFAULT).rstrip("/")


async def workbench_login(username: str, password: str) -> dict[str, Any]:
    """Proxy ``POST {base}/api/auth/login``; return the parsed body on success.

    Args:
        username: The workbench username.
        password: The workbench password.

    Returns:
        The workbench response dict; must contain a non-empty ``token``.

    Raises:
        WorkbenchAuthError: ``401`` for rejected credentials (workbench's
            Chinese detail passed through), ``503`` for timeout / connect
            failure, ``502`` for unexpected upstream status or malformed body.
    """
    import httpx

    url = f"{get_workbench_auth_base()}/api/auth/login"
    try:
        async with httpx.AsyncClient(timeout=WORKBENCH_LOGIN_TIMEOUT_S) as client:
            resp = await client.post(url, json={"username": username, "password": password})
    except httpx.TimeoutException as exc:
        raise WorkbenchAuthError(503, "工作台登录服务暂不可用（超时），请稍后重试") from exc
    except httpx.HTTPError as exc:
        raise WorkbenchAuthError(503, "工作台登录服务暂不可用，请稍后重试") from exc

    if resp.status_code == 401:
        detail = "用户名或密码不对"
        try:
            body = resp.json()
            if isinstance(body, dict) and str(body.get("detail") or "").strip():
                detail = str(body["detail"])
        except Exception:
            pass
        raise WorkbenchAuthError(401, detail)
    if resp.status_code != 200:
        raise WorkbenchAuthError(502, "工作台登录服务暂不可用，请稍后重试")

    try:
        body = resp.json()
    except Exception as exc:
        raise WorkbenchAuthError(502, "工作台登录响应异常，请稍后重试") from exc
    if not isinstance(body, dict) or not str(body.get("token") or "").strip():
        raise WorkbenchAuthError(502, "工作台登录响应异常，请稍后重试")
    return body


async def workbench_me(token: str) -> dict[str, Any]:
    """Verify a workbench token via ``GET {base}/api/auth/me``; return identity.

    1.4.18 account sync: the shell iframe shim captures the workbench login
    token (``wb_token``); the gateway verifies it server-side before minting
    a shell JWT. Error contract mirrors :func:`workbench_login`.

    Args:
        token: The workbench token (``Authorization: Bearer`` upstream). Never
            logged by this module or its callers.

    Returns:
        ``{"username": str, "role": str | None}`` — the workbench identity.

    Raises:
        WorkbenchAuthError: ``401`` when the workbench rejects the token
            (401/403 upstream → "工作台登录已失效"), ``503`` for timeout /
            connect failure, ``502`` for unexpected upstream status or a
            body without a non-empty ``username``.
    """
    import httpx

    url = f"{get_workbench_auth_base()}/api/auth/me"
    try:
        async with httpx.AsyncClient(timeout=WORKBENCH_LOGIN_TIMEOUT_S) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException as exc:
        raise WorkbenchAuthError(503, "工作台登录服务暂不可用（超时），请稍后重试") from exc
    except httpx.HTTPError as exc:
        raise WorkbenchAuthError(503, "工作台登录服务暂不可用，请稍后重试") from exc

    if resp.status_code in (401, 403):
        raise WorkbenchAuthError(401, "工作台登录已失效，请在工作台重新登录")
    if resp.status_code != 200:
        raise WorkbenchAuthError(502, "工作台登录服务暂不可用，请稍后重试")

    try:
        body = resp.json()
    except Exception as exc:
        raise WorkbenchAuthError(502, "工作台登录响应异常，请稍后重试") from exc
    username = str(body.get("username") or "").strip() if isinstance(body, dict) else ""
    if not username:
        raise WorkbenchAuthError(502, "工作台登录响应异常，请稍后重试")
    role = None
    if isinstance(body, dict):
        role = str(body.get("role") or "").strip().lower() or None
    return {"username": username, "role": role}
