"""工作台工单：待确认草稿仓储 + 人工确认派单（唯一 HTTP 派单入口）。

红线：
- ``draft_workbench_order`` / ``save_pending_draft`` 只落本地草稿，绝不发工作台 HTTP；
- 只有 ``confirm_pending_draft``（经人点「确认派单」）才调用派单函数；
- 同 ``external_ref`` 二次确认返回缓存结果，不再次 dispatch（防双扣）。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from evoflow.admin.ui_extensions_registry import config_dir

_LOCK = threading.Lock()
_STORE_NAME = "workbench_order_drafts.json"

DispatchFn = Callable[[dict[str, Any]], dict[str, Any]]


def _store_path(root: Path | None = None) -> Path:
    base = root if root is not None else config_dir()
    return Path(base) / "opsboard" / _STORE_NAME


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"drafts": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"drafts": {}}
    drafts = raw.get("drafts") if isinstance(raw, dict) else None
    if not isinstance(drafts, dict):
        return {"drafts": {}}
    return {"drafts": drafts}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _normalize_draft(draft: dict[str, Any]) -> dict[str, Any]:
    ref = str(draft.get("external_ref") or "").strip()
    if not ref:
        raise ValueError("external_ref 不能为空")
    out = dict(draft)
    out["external_ref"] = ref
    out["type"] = str(out.get("type") or "custom")[:20]
    out["status"] = "draft"
    out.setdefault("name", "")
    out.setdefault("description", "")
    out.setdefault("product", "")
    out.setdefault("qty", "")
    out.setdefault("requirements", "")
    out.setdefault("acceptance", "")
    out.setdefault("budget", "")
    out.setdefault("due", "")
    out.setdefault("assigned_role", "")
    out.setdefault("assigned_to", "")
    return out


def save_pending_draft(draft: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """落本地待确认草稿。不发 HTTP、不扣费。"""
    normalized = _normalize_draft(draft)
    ref = normalized["external_ref"]
    path = _store_path(root)
    with _LOCK:
        data = _read(path)
        existing = data["drafts"].get(ref)
        if isinstance(existing, dict) and existing.get("status") == "confirmed":
            # 已确认的不覆盖为 draft，避免误把已派单改回待确认
            return dict(existing)
        row = {
            **normalized,
            "status": "draft",
            "saved_at": time.time(),
            "confirmed_at": None,
            "dispatch_result": None,
        }
        data["drafts"][ref] = row
        _write(path, data)
        return dict(row)


def list_pending_drafts(*, root: Path | None = None, include_confirmed: bool = False) -> list[dict[str, Any]]:
    path = _store_path(root)
    with _LOCK:
        data = _read(path)
    rows = list(data["drafts"].values())
    if not include_confirmed:
        rows = [r for r in rows if isinstance(r, dict) and r.get("status") == "draft"]
    rows.sort(key=lambda r: float(r.get("saved_at") or 0), reverse=True)
    return [dict(r) for r in rows if isinstance(r, dict)]


def get_draft(external_ref: str, *, root: Path | None = None) -> dict[str, Any] | None:
    ref = str(external_ref or "").strip()
    if not ref:
        return None
    path = _store_path(root)
    with _LOCK:
        data = _read(path)
        row = data["drafts"].get(ref)
    return dict(row) if isinstance(row, dict) else None


def build_dispatch_payload(draft: dict[str, Any]) -> dict[str, Any]:
    """对齐工作台 ``POST /api/opsboard/dispatch`` body。"""
    ref = str(draft.get("external_ref") or "").strip()
    name = str(draft.get("name") or "").strip() or f"工单 {ref}"
    description = str(draft.get("description") or "").strip()
    payload: dict[str, Any] = {
        "name": name[:120],
        "description": description[:4000],
        "external_ref": ref,
        "type": str(draft.get("type") or "custom")[:20],
        "product": str(draft.get("product") or "")[:120],
        "qty": str(draft.get("qty") or "")[:60],
        "requirements": str(draft.get("requirements") or "")[:2000],
        "acceptance": str(draft.get("acceptance") or "")[:2000],
        "budget": str(draft.get("budget") or "")[:20],
        "due": str(draft.get("due") or "")[:60],
        "assigned_role": str(draft.get("assigned_role") or "")[:60],
        "assigned_to": str(draft.get("assigned_to") or "")[:60],
    }
    return payload


def confirm_pending_draft(
    external_ref: str,
    *,
    dispatch_fn: DispatchFn,
    root: Path | None = None,
    confirmed_by: str = "user",
) -> dict[str, Any]:
    """人工确认后派单。同号已确认则返回缓存，不再次调用 ``dispatch_fn``。"""
    ref = str(external_ref or "").strip()
    if not ref:
        raise ValueError("external_ref 不能为空")
    if dispatch_fn is None:
        raise ValueError("dispatch_fn 必填")

    path = _store_path(root)
    with _LOCK:
        data = _read(path)
        row = data["drafts"].get(ref)
        if not isinstance(row, dict):
            raise LookupError(f"找不到待确认草稿：{ref}")
        if row.get("status") == "confirmed" and isinstance(row.get("dispatch_result"), dict):
            cached = dict(row["dispatch_result"])
            cached["deduped"] = True
            cached["external_ref"] = ref
            return cached

        payload = build_dispatch_payload(row)
        # 在锁外调 HTTP 前先标记 confirming，避免并发双发：先写占位
        if row.get("status") == "confirming":
            raise RuntimeError("该工单正在确认派单中，请稍候")
        row = dict(row)
        row["status"] = "confirming"
        row["confirming_by"] = str(confirmed_by or "user")[:60]
        data["drafts"][ref] = row
        _write(path, data)

    try:
        result = dispatch_fn(payload)
    except Exception:
        with _LOCK:
            data = _read(path)
            cur = data["drafts"].get(ref)
            if isinstance(cur, dict) and cur.get("status") == "confirming":
                cur = dict(cur)
                cur["status"] = "draft"
                cur.pop("confirming_by", None)
                data["drafts"][ref] = cur
                _write(path, data)
        raise

    if not isinstance(result, dict):
        result = {"raw": result}
    out = dict(result)
    out["external_ref"] = ref
    out["deduped"] = False

    with _LOCK:
        data = _read(path)
        cur = data["drafts"].get(ref) or {}
        cur = dict(cur) if isinstance(cur, dict) else {"external_ref": ref}
        cur["status"] = "confirmed"
        cur["confirmed_at"] = time.time()
        cur["confirmed_by"] = str(confirmed_by or "user")[:60]
        cur["dispatch_result"] = out
        cur.pop("confirming_by", None)
        data["drafts"][ref] = cur
        _write(path, data)
    return out


def filter_orders_by_ref(orders: list[dict[str, Any]], external_ref: str) -> list[dict[str, Any]]:
    ref = str(external_ref or "").strip()
    if not ref:
        return []
    matched = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        if str(o.get("external_ref") or "").strip() == ref:
            matched.append(dict(o))
    return matched
