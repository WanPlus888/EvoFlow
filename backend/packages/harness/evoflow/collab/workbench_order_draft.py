"""一句话 → 结构化工单草稿（纯函数，无 DB / 无网络）。

字段与工单台 `POST /api/opsboard/dispatch` body 对齐，但本模块不发 HTTP；
真正的派单与确认流留给后续切片。
"""

from __future__ import annotations

import re
from datetime import datetime

# ---------------------------------------------------------------------------
# 常量（与工单台 tpl 对齐）
# ---------------------------------------------------------------------------

ORDER_TYPES = ("image", "video", "tuwen", "custom")

TPL_LABEL = {
    "image": "套图",
    "video": "短视频",
    "tuwen": "图文带货",
    "custom": "自定义",
}

TPL_API = {
    "image": "建单接口：POST /api/batch/jobs（type=image，body 带 external_ref=本工单号）",
    "video": "建单接口：短视频工作区建单（config.external_ref=本工单号），或直接派生视频任务",
    "tuwen": "建单接口：POST /api/plan/tuwen 生产图文（记录 external_ref=本工单号）",
    "custom": "按任务描述执行；如需建生产记录，一律带 external_ref=本工单号",
}

ROLE_BY_TYPE = {
    "image": "tuantu-op",
    "video": "shipin-op",
    "tuwen": "tuantu-op",  # 图文暂挂套图岗（阶段2不新开岗）
    "custom": "",
}

DEFAULT_ACCEPTANCE = {
    "image": "主图清晰、主体完整、无违禁元素；数量与要求角度齐套",
    "video": "时长与口播要点齐套；成片可播、无黑屏爆音",
    "tuwen": "标题合规、卖点齐全、配图与正文一致",
    "custom": "按要求完成并可对照验收",
}

# ---------------------------------------------------------------------------
# 工单号
# ---------------------------------------------------------------------------


def new_external_ref(*, now: datetime | None = None) -> str:
    """工单号，格式与工单台 `genRef` 一致：``EV-YYYYMMDD-HHMMSS``。"""
    ts = now if now is not None else datetime.now()
    return ts.strftime("EV-%Y%m%d-%H%M%S")


# ---------------------------------------------------------------------------
# 类型推断
# ---------------------------------------------------------------------------

_VIDEO_WORDS = ("短视频", "口播", "成片", "15秒", "30秒")
_IMAGE_WORDS = ("套图", "主图", "详情图", "出图", "张主图", "张图")
_TUWEN_WORDS = ("小红书", "图文", "笔记", "种草文")


def infer_order_type(text: str) -> str:
    """确定性关键词规则推断工单类型，先匹配更具体的。"""
    t = text.lower()
    has_video = any(w in t for w in _VIDEO_WORDS) or "视频" in t
    has_image = any(w in t for w in _IMAGE_WORDS)
    if has_video and not has_image:
        return "video"
    if any(w in t for w in _TUWEN_WORDS):
        return "tuwen"
    if has_image:
        return "image"
    return "custom"


# ---------------------------------------------------------------------------
# 字段抽取
# ---------------------------------------------------------------------------

_PRODUCT_RE = re.compile(r"(?:给|为|把)\s*([^，,。；;、\s]{2,20}?)(?=\s*(?:出|拍|写|做|来|要|$|[，,。；;、]))")
_QTY_RE = re.compile(r"(\d+)\s*[张条篇个]")
_BUDGET_RE = re.compile(r"(?:预算(?:上限)?|预算\s*)\s*(\d+)|(\d+)\s*元")
_DUE_RE = re.compile(r"(今天|明天|后天|本周|下周|周[一二三四五六日天]|今晚|今晚之前)")


def _extract_product(text: str) -> str:
    m = _PRODUCT_RE.search(text)
    if m:
        return m.group(1).strip()
    # 「这个品/该品」无法给出具体品名 → 留空
    return ""


def _extract_qty(text: str) -> str:
    m = _QTY_RE.search(text)
    return m.group(1) if m else ""


def _extract_budget(text: str) -> str:
    m = _BUDGET_RE.search(text)
    if not m:
        return ""
    return m.group(1) or m.group(2) or ""


def _extract_due(text: str) -> str:
    m = _DUE_RE.search(text)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# 派单描述
# ---------------------------------------------------------------------------


def format_dispatch_description(draft: dict) -> str:
    """对齐工单台 `buildDescription` 行格式；空字段行省略。"""
    otype = draft.get("type", "custom")
    label = TPL_LABEL.get(otype, TPL_LABEL["custom"])
    lines = [
        f"【工单号 {draft.get('external_ref', '')}】类型：{label}",
    ]
    if draft.get("product"):
        lines.append(f"产品：{draft['product']}")
    if draft.get("qty"):
        lines.append(f"数量/规模：{draft['qty']}")
    if draft.get("requirements"):
        lines.append(f"要求与卖点：{draft['requirements']}")
    if draft.get("acceptance"):
        lines.append(f"验收标准：{draft['acceptance']}")
    if draft.get("budget"):
        lines.append(f"预算上限：{draft['budget']} 元（仅记录，超支前请示）")
    if draft.get("due"):
        lines.append(f"交期：{draft['due']}")

    lines.append("")
    lines.append(TPL_API.get(otype, TPL_API["custom"]))
    lines.append(
        "执行要求：先用工作台产品档案核对外观事实；"
        "建单必须带 external_ref=本工单号；同号重放勿重复扣费；完成后回报工单号。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def parse_one_liner_to_order_draft(
    text: str,
    *,
    now: datetime | None = None,
    external_ref: str | None = None,
) -> dict:
    """把一句中文诉求解析为结构化工单草稿（不含真实派单）。"""
    src = (text or "").strip()
    otype = infer_order_type(src)

    ref = external_ref if external_ref else new_external_ref(now=now)
    product = _extract_product(src)
    qty = _extract_qty(src)
    budget = _extract_budget(src)
    due = _extract_due(src)
    requirements = src  # 精简版暂保留原句

    needs_confirm_fields: list[str] = []
    if not product:
        needs_confirm_fields.append("product")
    if otype == "custom" and len(src) < 6:
        needs_confirm_fields.append("text_too_short")
    if not qty and not budget:
        needs_confirm_fields.append("qty_or_budget")
    needs_confirm = bool(needs_confirm_fields)

    draft: dict = {
        "type": otype,
        "external_ref": ref,
        "product": product,
        "qty": qty,
        "requirements": requirements,
        "acceptance": DEFAULT_ACCEPTANCE[otype],
        "budget": budget,
        "due": due,
        "assigned_role": ROLE_BY_TYPE[otype],
        "assigned_to": "",
        "name": "",
        "needs_confirm": needs_confirm,
        "needs_confirm_fields": needs_confirm_fields,
        "source_text": src,
    }

    label = TPL_LABEL[otype]
    if product:
        draft["name"] = " ".join([ref, product, f"{label}工单"]).strip()
    else:
        draft["name"] = f"{label}工单"

    draft["description"] = format_dispatch_description(draft)
    return draft
