# -*- coding: utf-8 -*-  # noqa: UP009
"""AI 运营大脑 · 工单概览 / 确认派单 / 跟单验收代理（fork 扩展）。

- GET  /api/opsboard/summary — 驾驶舱 KPI
- GET/POST /api/opsboard/drafts — 待确认草稿（本地，零工作台 HTTP）
- POST /api/opsboard/drafts/{ref}/confirm — **唯一**扣费派单入口（人点确认）
- GET  /api/opsboard/orders/by-ref/{ref} — 按工单号跟单
- POST /api/opsboard/orders/{id}/approve|reject — 验收代理（人点）

凭据走环境变量 EVOFLOW_WORKBENCH_URL/USER/PASS（systemd 注入，不进代码/文档）。
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/opsboard", tags=["opsboard"])

_base = ""
_user = ""
_pass = ""
_token = ""
_role = ""
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
    global _token, _role, _token_at
    base, user, pw = _conf()
    if not user or not pw:
        raise RuntimeError("未配置 EVOFLOW_WORKBENCH_USER/PASS")
    r = _client_get().post(
        base + "/api/auth/login",
        json={"username": user, "password": pw, "remember": True},
    )
    r.raise_for_status()
    response = r.json()
    _token = str(response.get("token") or "")
    _role = str(response.get("role") or "")
    _token_at = time.time()
    if not _token:
        raise RuntimeError("登录未返回 token")
    return _token


def _require_workbench_admin() -> None:
    if not _token or time.time() - _token_at > 3600:
        _login()
    if _role != "admin":
        raise RuntimeError("工作台代理账号必须是管理员")


def _workbench_auth_headers() -> dict[str, str]:
    _require_workbench_admin()
    return {"Authorization": f"Bearer {_token}"}


def _authed_get(path: str) -> dict:
    global _token
    base, _, _ = _conf()
    if not _token or time.time() - _token_at > 3600:
        _login()
    r = _client_get().get(base + path, headers={"Authorization": f"Bearer {_token}"})
    if r.status_code == 401:
        _login()
        r = _client_get().get(base + path, headers={"Authorization": f"Bearer {_token}"})
    r.raise_for_status()
    return r.json()


def _authed_post(path: str, payload: dict) -> dict:
    global _token
    base, _, _ = _conf()
    if not _token or time.time() - _token_at > 3600:
        _login()
    r = _client_get().post(
        base + path,
        headers={"Authorization": f"Bearer {_token}"},
        json=payload,
    )
    if r.status_code == 401:
        _login()
        r = _client_get().post(
            base + path,
            headers={"Authorization": f"Bearer {_token}"},
            json=payload,
        )
    r.raise_for_status()
    return r.json()


def _dispatch_to_workbench(payload: dict[str, Any]) -> dict[str, Any]:
    """唯一真正打到工作台 create_and_dispatch 的函数。"""
    return _authed_post("/api/opsboard/dispatch", payload)


@router.get("/summary")
async def opsboard_summary() -> dict:
    base, user, _ = _conf()
    if not user:
        return {"configured": False, "detail": "未配置工作台代理账号"}
    try:
        data = _authed_get("/api/opsboard/orders?limit=200")
    except Exception as exc:
        return {
            "configured": True,
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}"[:120],
        }
    orders = data.get("orders") or []
    running = {"running", "analyzing", "queued", "pending"}
    wait = sum(
        1
        for o in orders
        if not (o.get("review") or {}).get("status") and o.get("type") != "ops_order"
    )
    summary = {
        "configured": True,
        "ok": True,
        "updated": time.time(),
        "total": len(orders),
        "wait_review": wait,
        "running": sum(1 for o in orders if o.get("status") in running),
        "approved": sum(1 for o in orders if (o.get("review") or {}).get("status") == "approved"),
        "rejected": sum(1 for o in orders if (o.get("review") or {}).get("status") == "rejected"),
        "over_budget": sum(1 for o in orders if o.get("over")),
        "spend": round(sum(o.get("cost") or 0 for o in orders), 2),
    }
    return summary


class DraftBody(BaseModel):
    draft: dict[str, Any] = Field(default_factory=dict)


class ReviewBody(BaseModel):
    note: str = ""


@router.get("/drafts")
async def list_drafts(include_confirmed: bool = False) -> dict:
    from evoflow.collab.workbench_order_confirm import list_pending_drafts

    rows = list_pending_drafts(include_confirmed=include_confirmed)
    return {"ok": True, "drafts": rows, "count": len(rows)}


@router.post("/drafts")
async def upsert_draft(body: DraftBody) -> dict:
    """保存/更新待确认草稿。本路由不调用工作台派单接口。"""
    from evoflow.collab.workbench_order_confirm import save_pending_draft

    try:
        row = save_pending_draft(body.draft or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "draft": row}


@router.post("/drafts/{external_ref}/confirm")
async def confirm_draft(external_ref: str) -> dict:
    """人工确认派单 → POST 工作台 /api/opsboard/dispatch。同号幂等。"""
    from evoflow.collab.workbench_order_confirm import confirm_pending_draft

    _, user, _ = _conf()
    if not user:
        raise HTTPException(status_code=503, detail="未配置工作台代理账号")
    try:
        result = confirm_pending_draft(
            external_ref,
            dispatch_fn=_dispatch_to_workbench,
            confirmed_by="user",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"工作台派单失败 HTTP {exc.response.status_code}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"工作台派单失败：{type(exc).__name__}: {exc}"[:200],
        ) from exc
    return {"ok": True, "result": result}


@router.get("/orders/by-ref/{external_ref}")
async def orders_by_ref(external_ref: str) -> dict:
    from evoflow.collab.workbench_order_confirm import filter_orders_by_ref

    _, user, _ = _conf()
    if not user:
        return {"configured": False, "orders": [], "detail": "未配置工作台代理账号"}
    try:
        data = _authed_get("/api/opsboard/orders?limit=200")
    except Exception as exc:
        return {
            "configured": True,
            "ok": False,
            "orders": [],
            "detail": f"{type(exc).__name__}: {exc}"[:120],
        }
    orders = filter_orders_by_ref(list(data.get("orders") or []), external_ref)
    return {
        "configured": True,
        "ok": True,
        "external_ref": external_ref,
        "orders": orders,
        "count": len(orders),
    }


@router.post("/orders/{order_id}/approve")
async def approve_order(order_id: str, body: ReviewBody | None = None) -> dict:
    _, user, _ = _conf()
    if not user:
        raise HTTPException(status_code=503, detail="未配置工作台代理账号")
    note = (body.note if body else "") or ""
    try:
        result = _authed_post(
            f"/api/opsboard/orders/{order_id}/approve",
            {"note": note[:500]},
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="工作台验收失败",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200]) from exc
    return {"ok": True, "result": result}


@router.post("/orders/{order_id}/reject")
async def reject_order(order_id: str, body: ReviewBody | None = None) -> dict:
    _, user, _ = _conf()
    if not user:
        raise HTTPException(status_code=503, detail="未配置工作台代理账号")
    note = (body.note if body else "") or ""
    try:
        result = _authed_post(
            f"/api/opsboard/orders/{order_id}/reject",
            {"note": note[:500]},
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="工作台打回失败",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200]) from exc
    return {"ok": True, "result": result}
