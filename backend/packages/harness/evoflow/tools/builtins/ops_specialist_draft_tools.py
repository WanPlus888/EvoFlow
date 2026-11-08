"""工单验收 / 知识沉淀草稿工具（多 Bot 分岗 P0 · 1.4.13 · 只产 draft payload）。

- ``ticket_accept_note_draft`` / ``ticket_todo_draft``：工单验收专员专用；
  只产本地草稿（不关单、不改工单生产状态；评论 API 待工作台接入）；
- ``team_knowledge_propose_draft``：知识沉淀专员专用；summary 截断 ≤300；
  **本模块内禁止调用任何 confirm/accept**——确认仅 admin 在工作台知识库
  UI 人工完成（propose→draft；confirm 另闸）。

全部工具零 HTTP 出站、零扣费、零真派；本地落盘 best-effort（失败不炸返回）。
"""

from __future__ import annotations

import json
import threading
import time

from langchain.tools import tool

_LOCK = threading.Lock()


def _persist_best_effort(payload: dict) -> None:
    """本地 pending 落盘（config_dir()/ops_specialist/drafts.json），失败忽略。"""
    try:
        from pathlib import Path

        from evoflow.admin.ui_extensions_registry import config_dir

        path = Path(config_dir()) / "ops_specialist" / "drafts.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            rows = []
            if path.is_file():
                try:
                    rows = json.loads(path.read_text(encoding="utf-8")).get("items", [])
                except (OSError, json.JSONDecodeError):
                    rows = []
            rows.append({**payload, "saved_at": time.time()})
            path.write_text(
                json.dumps({"items": rows[-500:]}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception:
        pass


@tool(
    "ticket_accept_note_draft",
    description=(
        "生成工单验收笔记草稿：把验收结论（result=pass|fail|needs_review）与"
        "备注整理为结构化草稿（JSON，status=draft）。只产本地草稿——"
        "不关单、不改工单生产状态、不发评论 API（待工作台接评论 API 后再升级）。"
    ),
    parse_docstring=False,
)
def ticket_accept_note_draft(ticket_ref: str, note: str, result: str = "needs_review", todos: str = "") -> str:
    """工单验收笔记草稿（只 draft，无关单生产写）。"""
    res = str(result or "").strip().lower()
    if res not in ("pass", "fail", "needs_review"):
        res = "needs_review"
    payload = {
        "kind": "ticket_accept_note_draft",
        "ticket_ref": str(ticket_ref or "").strip()[:120],
        "result": res,
        "note": str(note or "").strip()[:4000],
        "todos": str(todos or "").strip()[:2000],
        "status": "draft",
        "next_step": "草稿已保存；评论/关单须人工在工作台完成（本工具不接生产 API）",
    }
    _persist_best_effort(payload)
    return json.dumps(payload, ensure_ascii=False)


@tool(
    "ticket_todo_draft",
    description=(
        "生成工单验收待办草稿（JSON，status=draft）：验收后需要跟进的事项清单。"
        "只产本地草稿，不创建任务、不派单、不扣费。"
    ),
    parse_docstring=False,
)
def ticket_todo_draft(ticket_ref: str, items: str) -> str:
    """工单验收待办草稿（只 draft，不建任务不派单）。"""
    payload = {
        "kind": "ticket_todo_draft",
        "ticket_ref": str(ticket_ref or "").strip()[:120],
        "items": str(items or "").strip()[:4000],
        "status": "draft",
        "next_step": "待办草稿已保存；正式建任务由人工确认（本工具不派单）",
    }
    _persist_best_effort(payload)
    return json.dumps(payload, ensure_ascii=False)


@tool(
    "team_knowledge_propose_draft",
    description=(
        "生成团队知识建议草稿（title + summary≤300 字，status=draft）。"
        "只 propose 不 confirm：本工具绝不自动 accept/入库；"
        "确认仅 admin 在工作台知识库 UI 人工完成。"
    ),
    parse_docstring=False,
)
def team_knowledge_propose_draft(title: str, summary: str, source: str = "") -> str:
    """团队知识建议草稿（propose→draft；禁自动 accept）。"""
    payload = {
        "kind": "team_knowledge_propose_draft",
        "title": str(title or "").strip()[:120],
        "summary": str(summary or "").strip()[:300],
        "source": str(source or "").strip()[:200],
        "status": "draft",
        "confirm_policy": "admin-only：确认须 admin 在工作台知识库 UI 人工完成；本工具不做 accept",
    }
    _persist_best_effort(payload)
    return json.dumps(payload, ensure_ascii=False)
