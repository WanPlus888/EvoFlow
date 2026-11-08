"""投放建议单本地草稿存储（多 Bot 分岗 P0 · 1.4.13）。

EVOFLOW_HOME 下的 JSON 小存储（与 ``workbench_order_confirm`` 同模式）：

- status 枚举 **只有** ``draft | pending_review | discarded``——
  刻意不存在 ``production`` / ``applied`` 状态：本存储永远不承载生产写；
- ``submit_for_review`` 仅把 ``draft → pending_review`` 并追加审计事件，
  **零 HTTP 出站**（不调任何投放平台 / 工作台投放接口）；
- 存储读写失败不炸主路径（调用方 best-effort 容错）。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from evoflow.admin.ui_extensions_registry import config_dir

_LOCK = threading.Lock()
_STORE_NAME = "ad_suggestion_drafts.json"

AD_DRAFT_STATUS_DRAFT = "draft"
AD_DRAFT_STATUS_PENDING_REVIEW = "pending_review"
AD_DRAFT_STATUS_DISCARDED = "discarded"
AD_DRAFT_STATUSES = frozenset(
    {AD_DRAFT_STATUS_DRAFT, AD_DRAFT_STATUS_PENDING_REVIEW, AD_DRAFT_STATUS_DISCARDED}
)

# 建议单动作枚举（建议值，非生产执行）
AD_SUGGESTION_ACTIONS = frozenset({"budget", "bid", "pause", "start", "other"})


def _store_path(root: Path | None = None) -> Path:
    base = root if root is not None else config_dir()
    return Path(base) / "ad_watch" / _STORE_NAME


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


def _now() -> float:
    return time.time()


def _new_draft_id() -> str:
    return f"ad-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def _clean_action(raw: Any) -> str:
    a = str(raw or "").strip().lower() or "other"
    return a if a in AD_SUGGESTION_ACTIONS else "other"


def _clean_str(raw: Any, limit: int) -> str:
    return str(raw if raw is not None else "").strip()[:limit]


def create_draft(
    *,
    action: str,
    product: str = "",
    target: str = "",
    current_value: str = "",
    suggested_value: str = "",
    reason: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """新建建议单草稿（status=draft）。只写本地 JSON，零 HTTP。"""
    draft_id = _new_draft_id()
    row: dict[str, Any] = {
        "draft_id": draft_id,
        "status": AD_DRAFT_STATUS_DRAFT,
        "action": _clean_action(action),
        "product": _clean_str(product, 120),
        "target": _clean_str(target, 200),
        "current_value": _clean_str(current_value, 60),
        "suggested_value": _clean_str(suggested_value, 60),
        "reason": _clean_str(reason, 1000),
        "created_at": _now(),
        "updated_at": _now(),
        "submitted_at": None,
        "events": [{"event": "created", "at": _now()}],
    }
    path = _store_path(root)
    with _LOCK:
        data = _read(path)
        data["drafts"][draft_id] = row
        _write(path, data)
    return dict(row)


def update_draft(
    draft_id: str,
    *,
    action: str = "",
    product: str = "",
    target: str = "",
    current_value: str = "",
    suggested_value: str = "",
    reason: str = "",
    root: Path | None = None,
) -> dict[str, Any] | None:
    """改草稿字段（仍 ``draft``）。仅 ``draft`` 状态可改；待复核后锁定。"""
    did = str(draft_id or "").strip()
    if not did:
        return None
    path = _store_path(root)
    with _LOCK:
        data = _read(path)
        row = data["drafts"].get(did)
        if not isinstance(row, dict):
            return None
        if row.get("status") != AD_DRAFT_STATUS_DRAFT:
            return {"error": "only_draft_editable", "status": row.get("status"), "draft_id": did}
        changed = False
        for key, val in (
            ("action", action),
            ("product", product),
            ("target", target),
            ("current_value", current_value),
            ("suggested_value", suggested_value),
            ("reason", reason),
        ):
            cleaned = _clean_str(val, 1000 if key == "reason" else (120 if key == "product" else 200))
            if key == "action":
                if val and _clean_action(val) != row.get("action"):
                    row["action"] = _clean_action(val)
                    changed = True
                continue
            if val and cleaned != row.get(key):
                row[key] = _clean_str(val, 1000 if key == "reason" else (120 if key == "product" else 200))
                changed = True
        if changed:
            row["updated_at"] = _now()
            row.setdefault("events", []).append({"event": "updated", "at": _now()})
            _write(path, data)
        return dict(row)


def get_draft(draft_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    did = str(draft_id or "").strip()
    if not did:
        return None
    path = _store_path(root)
    with _LOCK:
        data = _read(path)
    row = data["drafts"].get(did)
    return dict(row) if isinstance(row, dict) else None


def list_drafts(*, status: str = "", root: Path | None = None) -> list[dict[str, Any]]:
    st = str(status or "").strip().lower()
    if st and st not in AD_DRAFT_STATUSES:
        st = ""
    path = _store_path(root)
    with _LOCK:
        data = _read(path)
    rows = [r for r in data["drafts"].values() if isinstance(r, dict)]
    if st:
        rows = [r for r in rows if r.get("status") == st]
    rows.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
    return [dict(r) for r in rows]


def submit_for_review(
    draft_id: str, *, note: str = "", root: Path | None = None
) -> dict[str, Any] | None:
    """建议单提交人工复核：``draft → pending_review``（仅改本地状态 + 审计）。

    这不是上推送投放平台，也不产生任何生产写副作用；真正的执行由人在
    复核后自行决定（本存储无 production/applied 状态）。
    """
    did = str(draft_id or "").strip()
    if not did:
        return None
    path = _store_path(root)
    with _LOCK:
        data = _read(path)
        row = data["drafts"].get(did)
        if not isinstance(row, dict):
            return None
        status = row.get("status")
        if status != AD_DRAFT_STATUS_DRAFT:
            return {"error": "not_draft", "status": status, "draft_id": did}
        row["status"] = AD_DRAFT_STATUS_PENDING_REVIEW
        row["submitted_at"] = _now()
        row["updated_at"] = _now()
        event: dict[str, Any] = {"event": "submitted_for_review", "at": _now()}
        cleaned_note = _clean_str(note, 500)
        if cleaned_note:
            event["note"] = cleaned_note
        row.setdefault("events", []).append(event)
        _write(path, data)
        return dict(row)
