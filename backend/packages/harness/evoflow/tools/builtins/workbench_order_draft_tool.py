"""一句话 → 结构化工单草稿工具（只出草稿，不派单不扣费）。

本工具只做解析与草稿生成，并可选落本地待确认草稿；
绝不调用工作台派单接口、绝不扣费。
确认后的真正派单由人点「确认派单」→ ``POST /api/opsboard/drafts/{ref}/confirm``。
"""

import json

from langchain.tools import tool

from evoflow.collab.workbench_order_draft import parse_one_liner_to_order_draft

_DRAFT_WORKBENCH_ORDER_DESCRIPTION = """\
把用户一句话诉求解析为结构化工单草稿（JSON）。
只生成结构化工单草稿，绝不调用工作台派单接口，绝不扣费。
返回字段含 type/product/qty/budget/.../needs_confirm，status 固定为 draft；
needs_confirm 为 true 时请先向用户确认缺失字段；
字段齐全后请提示用户在聊天卡或「生产工单」页点「确认派单」（本工具不派单）。
"""


def _persist_draft_best_effort(draft: dict) -> None:
    """落本地待确认草稿，失败不影响工具返回（仍只是草稿）。"""
    try:
        from evoflow.collab.workbench_order_confirm import save_pending_draft

        save_pending_draft(draft)
    except Exception:
        pass


@tool("draft_workbench_order", description=_DRAFT_WORKBENCH_ORDER_DESCRIPTION, parse_docstring=False)
def draft_workbench_order(text: str, external_ref: str = "") -> str:
    """只生成结构化工单草稿，绝不调用工作台派单接口，绝不扣费。"""
    draft = parse_one_liner_to_order_draft(text, external_ref=external_ref or None)
    payload = dict(draft)
    payload["status"] = "draft"
    if payload.get("needs_confirm"):
        payload["next_step"] = "请向用户确认缺失字段后再派单（本工具不派单）"
    else:
        payload["next_step"] = (
            "已生成草稿，请用户在聊天「确认派单」或生产工单页确认（本工具不派单）"
        )
    # 仅本地落库；绝不 HTTP
    _persist_draft_best_effort(payload)
    return json.dumps(payload, ensure_ascii=False)
