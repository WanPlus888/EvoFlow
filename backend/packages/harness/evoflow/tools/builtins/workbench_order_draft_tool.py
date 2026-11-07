"""一句话 → 结构化工单草稿工具（只出草稿，不派单不扣费）。

本工具只做解析与草稿生成，绝不调用工作台派单接口、绝不扣费。
确认后的真正派单由工单台 / 后续切片承担。
"""

import json

from langchain.tools import tool

from evoflow.collab.workbench_order_draft import parse_one_liner_to_order_draft

_DRAFT_WORKBENCH_ORDER_DESCRIPTION = """\
把用户一句话诉求解析为结构化工单草稿（JSON）。
只生成结构化工单草稿，绝不调用工作台派单接口，绝不扣费。
返回字段含 type/product/qty/budget/.../needs_confirm，status 固定为 draft；
needs_confirm 为 true 时请先向用户确认缺失字段，确认后由工单台/后续切片派单。
"""


@tool("draft_workbench_order", description=_DRAFT_WORKBENCH_ORDER_DESCRIPTION, parse_docstring=False)
def draft_workbench_order(text: str, external_ref: str = "") -> str:
    """只生成结构化工单草稿，绝不调用工作台派单接口，绝不扣费。"""
    draft = parse_one_liner_to_order_draft(text, external_ref=external_ref or None)
    payload = dict(draft)
    payload["status"] = "draft"
    if payload.get("needs_confirm"):
        payload["next_step"] = "请向用户确认缺失字段后再派单（本工具不派单）"
    else:
        payload["next_step"] = "已生成草稿，待用户确认后由工单台/后续切片派单（本工具不派单）"
    return json.dumps(payload, ensure_ascii=False)
