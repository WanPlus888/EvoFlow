"""运营终端多 Bot 分岗 P0（1.4.13）：专员注册表 + 岗位种子（单一事实源）。

形态 C（主 Router + ``@专员`` / 专员卡片 / 转交卡）的岗位元数据与幂等种子：

- P0 五角色：运营大脑 Router、主图·套图、工单验收、知识沉淀、投放盯盘；
- ``ensure_ops_specialist_agents()`` 写 ``evoflow_agents``（复用
  ``workbench_role_agents.ensure_workbench_role_agents`` 的种子模式）；
- ``list_ops_specialists()`` / ``get_ops_specialist(code)`` 供注册表消费——
  **可扩展挂载点**：后续新增专员 = 在 ``_SPECIALIST_SPECS`` 加种子条目，
  不改 Router 主路径。

红线（总规划 §0 钉死口径，2026-11-09）：
- 投放盯盘「可写」= 建议单/草稿白名单（``AD_WATCH_DRAFT_TOOLS``）+ Gate；
  **禁止**任何投放平台生产写（改预算/出价/启停/建计划/传创意一律不做）；
- Router 不真派：只听/拆/转交；``draft_workbench_order`` 只草稿，
  无 workbench submit、无投放生产工具；
- 知识只有 propose draft；confirm 仅 admin + Gate（本刀不做自动 accept）；
- 草稿永不自动扣费、不自动真派（工具零 HTTP 出站）。

与 ``workbench_role_agents`` 的关系：
- ``tuantu-op`` / ``shipin-op`` / ``kefu-op`` 的 1.4.11/1.4.12 种子（选图优选 +
  挂搜描述）原样保留，本模块**不**重写它们；
- ``main-image-op`` 是「主图·套图专员」的 P0 别名 code，指向与 ``tuantu-op``
  同一工具集（见 ``MAIN_IMAGE_OP_ALIAS_OF``），不覆盖旧岗描述。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evoflow.collab.workbench_role_agents import (
    BASE_TOOLS,
    IMAGE_WORKBENCH_TOOLS,
    ROLE_RESEARCH_TOOLS,
    _dedupe_preserve_order,
)

# ── P0 专员 code（hyphen-case，符合 AGENT_NAME_PATTERN）───────────────
OPS_BRAIN_ROUTER = "ops-brain-router"
MAIN_IMAGE_OP = "main-image-op"
TICKET_ACCEPT_OP = "ticket-accept-op"
KNOWLEDGE_DEPOSIT_OP = "knowledge-deposit-op"
AD_WATCH_OP = "ad-watch-op"

# 「主图·套图专员」别名映射：新 code 指向旧生产岗同一工具集（不改 tuantu-op 种子）。
MAIN_IMAGE_OP_ALIAS_OF: dict[str, str] = {MAIN_IMAGE_OP: "tuantu-op"}

# ── 投放盯盘「可写」白名单（§0 钉死 · 禁区外才可写；纯本地草稿/建议单）──
AD_WATCH_DRAFT_TOOLS: list[str] = [
    "ad_watch_daily_draft",
    "ad_anomaly_card_draft",
    "ad_suggestion_draft_create",
    "ad_suggestion_draft_update",
    "ad_suggestion_draft_list",
    "ad_suggestion_draft_get",
    "ad_suggestion_submit_for_review",  # Gate：RISK_CONFIRM；仅 draft → pending_review，非生产写
]

# 工单验收 / 知识沉淀草稿工具（只产 draft payload；confirm 另闸）
TICKET_DRAFT_TOOLS: list[str] = [
    "ticket_accept_note_draft",
    "ticket_todo_draft",
]
KNOWLEDGE_PROPOSE_TOOLS: list[str] = [
    "team_knowledge_propose_draft",
    "knowledge_search",
    "knowledge_read",
]


@dataclass(frozen=True)
class OpsSpecialist:
    """P0 专员元数据（注册表条目）。tools 为岗位白名单（fail-closed 求交用）。"""

    code: str
    name: str
    short: str
    description: str
    tools: list[str] = field(default_factory=list)
    gate_note: str = ""  # 岗位 Gate 策略说明（敏感动作走 TOOL_RISK_LEVELS 确认卡）


_SPECIALISTS: tuple[OpsSpecialist, ...] = (
    OpsSpecialist(
        code=OPS_BRAIN_ROUTER,
        name="运营大脑",
        short="听需求、拆任务、按岗转交",
        description=(
            "运营大脑 Router（主对话）：倾听与拆解运营诉求，生成工单草稿"
            "（draft_workbench_order，只草稿不派单不扣费），并按岗转交给专员"
            "（转交只产 handoff 意图，不直接真派）。不持有任何工作台生产提交"
            "或投放生产工具；涉及花钱/真派的动作一律转确认卡。"
        ),
        tools=[*BASE_TOOLS],
        gate_note="无 workbench submit；无投放生产写；草稿零扣费",
    ),
    OpsSpecialist(
        code=MAIN_IMAGE_OP,
        name="主图·套图专员",
        short="商品主图/套图生成与跟踪",
        description=(
            "主图·套图专员（tuantu-op 的 P0 别名岗）：查商品档案、提交并跟踪"
            "单图生成。生产前必须 workbench_products_list 确认商品；省略 "
            "image_indexes 由服务端自动优选参考图，提交后回显 selected_indexes/"
            "select_layer/select_reason；用户说「用第 n 张」时显式传 [n] 覆盖。"
            "可只读检索外网；真正 submit 前会弹确认卡。"
        ),
        tools=_dedupe_preserve_order(
            [*BASE_TOOLS, *ROLE_RESEARCH_TOOLS, *IMAGE_WORKBENCH_TOOLS]
        ),
        gate_note="workbench_image_submit 仍 RISK_CONFIRM 确认卡",
    ),
    OpsSpecialist(
        code=TICKET_ACCEPT_OP,
        name="工单验收专员",
        short="验收笔记与待办草稿",
        description=(
            "工单验收专员：把验收结论整理为笔记草稿（ticket_accept_note_draft）"
            "与待办草稿（ticket_todo_draft）。只产本地草稿，不关单、不改工单"
            "生产状态；待工作台接评论 API 后再升级（本刀不接）。"
        ),
        tools=_dedupe_preserve_order([*BASE_TOOLS, *TICKET_DRAFT_TOOLS]),
        gate_note="无关单生产写；只有本地草稿",
    ),
    OpsSpecialist(
        code=KNOWLEDGE_DEPOSIT_OP,
        name="知识沉淀专员",
        short="团队知识建议草稿",
        description=(
            "知识沉淀专员：把可复用经验整理为团队知识建议草稿"
            "（team_knowledge_propose_draft，summary ≤300 字，status=draft），"
            "可先只读检索知识库（knowledge_search / knowledge_read）对齐已有条目。"
            "绝不自动 confirm/accept；确认仅 admin 在工作台知识库 UI 人工完成。"
        ),
        tools=_dedupe_preserve_order([*BASE_TOOLS, *KNOWLEDGE_PROPOSE_TOOLS]),
        gate_note="只有 propose draft；无 auto accept；confirm 仅 admin + Gate",
    ),
    OpsSpecialist(
        code=AD_WATCH_OP,
        name="投放盯盘专员",
        short="盯盘日报/异常卡/建议单草稿",
        description=(
            "投放盯盘专员（可写=建议单草稿白名单）：产出盯盘日报草稿"
            "（ad_watch_daily_draft）、异常卡片草稿（ad_anomaly_card_draft）与"
            "投放建议单草稿（预算/出价/启停的建议值，status=draft）。"
            "ad_suggestion_submit_for_review 仅把建议单提交人工复核"
            "（draft → pending_review，人点确认），不进任何投放平台生产写。"
            "指标快照字段允许为空（数据源待接），禁止为接数据去碰投放生产路径。"
        ),
        tools=_dedupe_preserve_order([*BASE_TOOLS, *AD_WATCH_DRAFT_TOOLS]),
        gate_note="可写 ⊆ ad_* 白名单 1–6；submit_for_review=RISK_CONFIRM；零生产写",
    ),
)

_SPECIALIST_BY_CODE: dict[str, OpsSpecialist] = {s.code: s for s in _SPECIALISTS}

# Router 之外可上「专员条」的岗位（壳侧卡片顺序与此一致）
STRIPE_SPECIALIST_CODES: list[str] = [
    MAIN_IMAGE_OP,
    TICKET_ACCEPT_OP,
    KNOWLEDGE_DEPOSIT_OP,
    AD_WATCH_OP,
]


def list_ops_specialists() -> list[OpsSpecialist]:
    """注册表全集（含 Router）；数据驱动，新增专员无需改调用方。"""
    return list(_SPECIALISTS)


def get_ops_specialist(code: str) -> OpsSpecialist | None:
    return _SPECIALIST_BY_CODE.get(str(code or "").strip())


def specialist_tools(code: str) -> list[str]:
    sp = get_ops_specialist(code)
    return list(sp.tools) if sp else []


def ensure_ops_specialist_agents() -> dict[str, list[str]]:
    """幂等写入 P0 专员配置到 ``evoflow_agents``。

    与 ``ensure_workbench_role_agents`` 同模式：已有 agent 覆盖
    ``agent_name`` / ``tools`` / ``agent_type`` / ``platform_scope``，
    其它字段原样保留；import 无副作用，写库由调用方触发。
    返回 ``{agent_code: tools}`` 便于测例断言（fail-closed 白名单求交）。
    """
    from evoflow.config.agents_config import (
        load_agent_config,
        save_agent_config,
    )

    try:
        from evoflow.config.agents_config import invalidate_agent_config_cache
    except ImportError:  # pragma: no cover - 防御旧布局
        invalidate_agent_config_cache = None  # type: ignore[assignment]

    out: dict[str, list[str]] = {}
    for sp in _SPECIALISTS:
        payload: dict[str, Any]
        try:
            cfg = load_agent_config(sp.code)
        except (FileNotFoundError, ValueError):
            cfg = None
        if cfg is not None:
            payload = cfg.model_dump(mode="python", exclude={"name"})
        else:
            payload = {"agent_code": sp.code, "description": sp.description}
        payload["agent_code"] = sp.code
        payload["agent_name"] = sp.name
        payload["agent_type"] = "custom"
        payload["tools"] = list(sp.tools)
        # L1 平台域：与生产两岗同款 custom-knowledge（专员工具均不涉平台动作）
        payload["platform_scope"] = {
            "mode": "custom",
            "domains": ["knowledge"],
            "actions": [],
            "max_risk": "write",
        }
        save_agent_config(sp.code, payload)
        if invalidate_agent_config_cache is not None:
            invalidate_agent_config_cache(sp.code)
        out[sp.code] = list(sp.tools)
    return out


if __name__ == "__main__":
    for code, tools in ensure_ops_specialist_agents().items():
        print(f"{code}: {len(tools)} tools")
