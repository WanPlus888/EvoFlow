# -*- coding: utf-8 -*-
"""电商运营终端 · 工单概览代理（P1 驾驶舱合一，fork 扩展）。

终端首页「生产工单」概览条的数据面：网关服务端代理工作台 /api/opsboard/orders，
自动登录专用成员账号（凭据走环境变量 EVOFLOW_WORKBENCH_URL/USER/PASS，
systemd 注入，不进代码/文档），会话令牌进程内缓存、401 自动重登。

失败语义：工作台不可达/未配置时返回 configured=false，前端渲染降级提示。
"""
import os
import time

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/opsboard", tags=["opsboard"])

_base = ""
_user = ""
_pass = ""
_token = ""
_token_at = 0.0
_client: httpx.Client | None = None


def _conf() -> tuple[str, str, str]:
    global _base, _user, _pass
    if not _base:
        _base = os.getenv("EVOFLOW_WORKBENCH_URL", "http://127.0.0.1:8790").rstrip("/")
        _user = os.getenv("EVOFLOW_WORKBENCH_USER", "")
        _pass = os.getenv("EVOFLOW_WORKBENCH_PASS", "")
    return _base, _user, _pass


def _client_get() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=8)
    return _client


def _login() -> str:
    global _token, _token_at
    base, user, pw = _conf()
    if not user or not pw:
        raise RuntimeError("未配置 EVOFLOW_WORKBENCH_USER/PASS")
    r = _client_get().post(base + "/api/auth/login",
                           json={"username": user, "password": pw, "remember": True})
    r.raise_for_status()
    _token = str(r.json().get("token") or "")
    _token_at = time.time()
    if not _token:
        raise RuntimeError("登录未返回 token")
    return _token


def _authed_get(path: str) -> dict:
    global _token
    base, _, _ = _conf()
    if not _token or time.time() - _token_at > 3600:
        _login()
    r = _client_get().get(base + path,
                          headers={"Authorization": f"Bearer {_token}"})
    if r.status_code == 401:
        _login()
        r = _client_get().get(base + path,
                              headers={"Authorization": f"Bearer {_token}"})
    r.raise_for_status()
    return r.json()


@router.get("/summary")
async def opsboard_summary() -> dict:
    base, user, _ = _conf()
    if not user:
        return {"configured": False, "detail": "未配置工作台代理账号"}
    try:
        data = _authed_get("/api/opsboard/orders?limit=200")
    except Exception as exc:
        return {"configured": True, "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"[:120]}
    orders = data.get("orders") or []
    running = {"running", "analyzing", "queued", "pending"}
    wait = sum(1 for o in orders
               if not (o.get("review") or {}).get("status") and o.get("type") != "ops_order")
    summary = {
        "configured": True, "ok": True, "updated": time.time(),
        "total": len(orders),
        "wait_review": wait,
        "running": sum(1 for o in orders if o.get("status") in running),
        "approved": sum(1 for o in orders if (o.get("review") or {}).get("status") == "approved"),
        "rejected": sum(1 for o in orders if (o.get("review") or {}).get("status") == "rejected"),
        "over_budget": sum(1 for o in orders if o.get("over")),
        "spend": round(sum(o.get("cost") or 0 for o in orders), 2),
    }
    return summary
