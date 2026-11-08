"""投放盯盘白名单工具 1–6（多 Bot 分岗 P0 · 1.4.13 · 纯本地草稿）。

钉死口径（总规划 §0「投放盯盘可写白名单」）：
- 允许：本地草稿 / 建议单（落 EVOFLOW_HOME 本地存储），**零**投放平台 HTTP；
- Gate：``ad_suggestion_submit_for_review`` = RISK_CONFIRM（人点确认才
  ``draft → pending_review``），仍不进生产；
- 硬禁止：本模块及 import 图不得出现任何投放平台生产写（改预算/出价/启停/
  建计划/传创意到投放后台的调用与路由）——测例按符号黑名单零命中验收。

指标快照字段为占位：P0 数据源待接，允许为空，UI/描述写明「数据源待接」；
不得为接数据去碰投放生产路径。
"""

from __future__ import annotations

import json

from langchain.tools import tool

from evoflow.collab import ad_suggestion_draft_store as store

_DATA_SOURCE_NOTE = "指标快照为占位字段（数据源待接，允许为空）"


@tool(
    "ad_watch_daily_draft",
    description=(
        "生成投放盯盘日报草稿（摘要文本 + 指标快照占位字段，纯本地草稿）。"
        "不调用任何投放平台接口、不产生生产写；指标快照数据源待接，允许为空。"
        "返回 JSON 草稿，status=draft。"
    ),
    parse_docstring=False,
)
def ad_watch_daily_draft(summary: str, date: str = "", metrics_snapshot: str = "") -> str:
    """生成盯盘日报草稿（纯本地，零 HTTP）。"""
    row = {
        "kind": "ad_watch_daily_draft",
        "date": str(date or "").strip()[:20],
        "summary": str(summary or "").strip()[:4000],
        "metrics_snapshot": str(metrics_snapshot or "").strip()[:4000] or None,
        "metrics_note": _DATA_SOURCE_NOTE,
        "status": "draft",
    }
    return json.dumps(row, ensure_ascii=False)


@tool(
    "ad_anomaly_card_draft",
    description=(
        "生成投放异常卡片草稿（异常类型/商品/建议文案，纯本地草稿）。"
        "不调用任何投放平台接口、不产生生产写；只帮助人快速记录异常。"
        "返回 JSON 草稿，status=draft。"
    ),
    parse_docstring=False,
)
def ad_anomaly_card_draft(anomaly_type: str, product: str = "", suggestion: str = "") -> str:
    """生成异常卡片草稿（纯本地，零 HTTP）。"""
    row = {
        "kind": "ad_anomaly_card_draft",
        "anomaly_type": str(anomaly_type or "").strip()[:60] or "unspecified",
        "product": str(product or "").strip()[:120],
        "suggestion": str(suggestion or "").strip()[:2000],
        "status": "draft",
    }
    return json.dumps(row, ensure_ascii=False)


@tool(
    "ad_suggestion_draft_create",
    description=(
        "新建投放建议单草稿：预算/出价/启停的**建议值**（action=budget|bid|pause|"
        "start|other），status=draft，落本地存储（EVOFLOW_HOME）。"
        "只是建议，绝不执行、不调用投放平台、不改生产计划。"
    ),
    parse_docstring=False,
)
def ad_suggestion_draft_create(
    action: str,
    target: str = "",
    suggested_value: str = "",
    product: str = "",
    current_value: str = "",
    reason: str = "",
) -> str:
    """新建建议单草稿（纯本地，零 HTTP，永不自动执行）。"""
    row = store.create_draft(
        action=action,
        product=product,
        target=target,
        current_value=current_value,
        suggested_value=suggested_value,
        reason=reason,
    )
    row["next_step"] = "草稿已保存；如需提交人工复核请用 ad_suggestion_submit_for_review（会弹确认卡）"
    return json.dumps(row, ensure_ascii=False)


@tool(
    "ad_suggestion_draft_update",
    description=(
        "修改投放建议单草稿字段（仍 status=draft；仅 draft 状态可改，"
        "提交复核后锁定）。纯本地存储，零投放平台调用。"
    ),
    parse_docstring=False,
)
def ad_suggestion_draft_update(
    draft_id: str,
    action: str = "",
    target: str = "",
    suggested_value: str = "",
    product: str = "",
    current_value: str = "",
    reason: str = "",
) -> str:
    """改建议单草稿字段（仍 draft；纯本地，零 HTTP）。"""
    row = store.update_draft(
        draft_id,
        action=action,
        product=product,
        target=target,
        current_value=current_value,
        suggested_value=suggested_value,
        reason=reason,
    )
    if row is None:
        return json.dumps({"error": "not_found", "draft_id": str(draft_id or "")}, ensure_ascii=False)
    return json.dumps(row, ensure_ascii=False)


@tool(
    "ad_suggestion_draft_list",
    description="列出投放建议单草稿（可按 status=draft|pending_review|discarded 过滤）。只读本地存储。",
    parse_docstring=False,
)
def ad_suggestion_draft_list(status: str = "") -> str:
    """列建议单草稿（只读本地）。"""
    rows = store.list_drafts(status=status)
    return json.dumps(
        {"count": len(rows), "items": rows, "note": "仅本地草稿；无生产状态"},
        ensure_ascii=False,
    )


@tool(
    "ad_suggestion_draft_get",
    description="按 draft_id 读单个投放建议单草稿。只读本地存储。",
    parse_docstring=False,
)
def ad_suggestion_draft_get(draft_id: str) -> str:
    """读建议单草稿（只读本地）。"""
    row = store.get_draft(draft_id)
    if row is None:
        return json.dumps({"error": "not_found", "draft_id": str(draft_id or "")}, ensure_ascii=False)
    return json.dumps(row, ensure_ascii=False)


@tool(
    "ad_suggestion_submit_for_review",
    description=(
        "把投放建议单草稿「提交人工复核」：仅把 status 从 draft 改为 "
        "pending_review（本地状态 + 审计事件），**不是**推送到投放平台，"
        "无任何生产写副作用。调用前会弹确认卡（RISK_CONFIRM）。"
    ),
    parse_docstring=False,
)
def ad_suggestion_submit_for_review(draft_id: str, note: str = "") -> str:
    """建议单提交人工复核（仅本地状态流转，零 HTTP，无生产写）。"""
    row = store.submit_for_review(draft_id, note=note)
    if row is None:
        return json.dumps({"error": "not_found", "draft_id": str(draft_id or "")}, ensure_ascii=False)
    return json.dumps(row, ensure_ascii=False)
