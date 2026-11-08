"""运营大脑缺口匹配（P1 能力扩展 · 口径A/D）：意图 → 已注册工具候选（纯函数核心）。

「缺口」= 用户一句话涉及工作台未直接覆盖 / 需调已注册 tool 的操作。本模块只做
**候选匹配**，不 invoke、不产出确认卡、不绕过任何门禁：

- 候选只来自 ``allowed_tools``（AgentConfig.tools ∩ 会话门禁的实时白名单）；
- 硬排除 ``GAP_MATCH_DENYLIST``（bash/terminal/process 族与不可逆删除）与高危 MCP
  （风险非 auto 的 ``mcp__*``）——确认卡根本不列出它们，不存在「降级展示仍一键执行」；
- 调用方（编排层/中间件）拿候选去发起 tool call：RISK_CONFIRM 工具仍由
  ToolApprovalMiddleware 弹确认卡（用户确认后才真正执行）；只读候选（web_search 等）
  按口径A 可直接跑（执行前调研）；
- 无候选 → 调用方用 ``format_no_match_reply()`` 的 P2 占位句自然语言说明，不调 bash 山寨；
- ``OPS_BRAIN_GAP_MATCH=0`` → ``match_registered_tools`` 恒返回 []（总开关/回滚兜底）。

P2（另刀，本 tip 只留占位，不自动改产）：拟议包 schema / 「转人工·派开发」钩子 /
观察模式 Gate，见 ``P2_PROPOSAL_STUB``。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# ── 开关 ──────────────────────────────────────────────────────


def gap_match_enabled() -> bool:
    """``OPS_BRAIN_GAP_MATCH=0`` → 关闭缺口自动匹配（工具仍可人手调用）。"""
    raw = os.environ.get("OPS_BRAIN_GAP_MATCH", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


# ── 数据形状 ──────────────────────────────────────────────────


@dataclass(frozen=True)
class GapMatch:
    """一个缺口匹配候选（只作展示/提示，绝不直接执行）。"""

    tool_name: str
    args_preview: dict = field(default_factory=dict)  # 脱敏摘要（当前为意图截断）
    risk: str = "auto"  # auto|session|confirm（展示用；执行闸仍走 tool_approval）
    reason: str = ""  # ≤200 字命中说明


# ── 硬排除（拍板口径D）─────────────────────────────────────────
# 不可进「缺口匹配确认候选」：shell/进程执行族与不可逆删除。
# bash 仍可走原有人工工具审批路径（非缺口匹配），此处只是不让匹配器推荐它。
GAP_MATCH_DENYLIST: frozenset[str] = frozenset({
    "bash",
    "terminal",
    "process",
    "process_start",
    "process_kill",
    "taskstop",
    "delete",
})


def is_high_risk_mcp(tool_name: str) -> bool:
    """高危 MCP 判定：``mcp__*`` 且风险非 auto → True。

    - destructiveHint → confirm：排除；
    - 无 annotations 的外部 MCP：能力未知，兜底 session（宁可不推荐）→ 排除；
    - readOnlyHint → auto 的只读 MCP 不排除，但候选仍须过 allowed_tools 白名单。
    风险不可判（异常）→ 按高危排除（fail-closed）。
    """
    name = str(tool_name or "").strip().lower()
    if not name.startswith("mcp__"):
        return False
    try:
        from evoflow.agents.tool_approval_config import RISK_AUTO, tool_risk_level

        return tool_risk_level(name) != RISK_AUTO
    except Exception:
        return True


# ── 意图词典（规则匹配，确定性可测；后续可叠轻量 LLM，本刀不引入）──

_GAP_INTENT_LEXICON: dict[str, tuple[str, ...]] = {
    "web_search": (
        "联网搜", "搜索一下", "搜一下", "网上查", "联网查", "查下最新", "最新消息",
        "行情", "趋势", "热门", "调研", "search", "web search",
    ),
    "fetch_url": ("打开链接", "打开网址", "这个链接", "网页内容", "url", "fetch_url"),
    "knowledge": ("知识库", "内部文档", "kb"),
    "workbench_products_list": ("商品档案", "产品档案", "查商品", "商品列表", "看下商品"),
    "workbench_image_submit": ("提交主图", "生成主图", "出图", "套图提交", "单图生成", "提交图片"),
    "workbench_image_status": ("图片状态", "出图状态", "单图进度", "图好了吗"),
    "workbench_video_options": ("视频供应商", "供应商能力", "视频模型", "可选模型"),
    "workbench_video_submit": ("提交视频", "生成视频", "短视频任务", "做视频", "提交短视频"),
    "workbench_video_status": ("视频状态", "视频进度", "视频好了吗"),
    "draft_workbench_order": ("工单草稿", "出草稿", "拟工单", "draft"),
}


def _normalized_intent(intent_text: str) -> str:
    return str(intent_text or "").strip().lower()


# ── 匹配核心 ──────────────────────────────────────────────────


def match_registered_tools(
    *,
    intent_text: str,
    allowed_tools: set[str],
    catalog: list[dict],
    max_candidates: int = 3,
) -> list[GapMatch]:
    """意图 → 白名单内候选（规则打分，确定性排序）。

    仅返回 ``allowed_tools`` 内、在 ``catalog`` 有登记、非 denylist、非高危 MCP 的候选；
    无候选 → 空列表（调用方提示转人工 / P2 占位文案）。打分：命中关键词按长度加权
    （长词更具体），多命中叠加；同分按名字典序稳定排序。
    """
    if not gap_match_enabled():
        return []
    text = _normalized_intent(intent_text)
    if not text:
        return []

    allowed = {str(t or "").strip().lower() for t in allowed_tools if str(t or "").strip()}
    registered = {
        str((e or {}).get("name") or "").strip().lower()
        for e in catalog or []
        if isinstance(e, dict) and str((e or {}).get("name") or "").strip()
    }

    from evoflow.agents.tool_approval_config import tool_risk_level

    scored: list[tuple[int, str, GapMatch]] = []
    for tool_name, keywords in _GAP_INTENT_LEXICON.items():
        if tool_name not in allowed or tool_name not in registered:
            continue
        if tool_name in GAP_MATCH_DENYLIST or is_high_risk_mcp(tool_name):
            continue  # 双保险：调用方白名单也不该放行，这里再拦一次
        hits = [kw for kw in keywords if kw in text]
        if not hits:
            continue
        score = sum(len(kw) for kw in hits) + 2 * len(hits)
        try:
            risk = tool_risk_level(tool_name)
        except Exception:
            risk = "confirm"  # 风险不可判按最高级展示（不阻断，只提示需确认）
        reason = f"意图命中：{'、'.join(hits[:4])}"
        scored.append(
            (
                score,
                tool_name,
                GapMatch(
                    tool_name=tool_name,
                    args_preview={"intent": text[:80]},
                    risk=str(risk),
                    reason=reason[:200],
                ),
            )
        )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [gap for _, _, gap in scored[: max(1, int(max_candidates))]]


def build_catalog_from_tools(tools) -> list[dict]:
    """从 LangChain 工具对象（或名字串）构建 ``[{name, description}]`` 目录。"""
    catalog: list[dict] = []
    for t in tools or []:
        name = str(getattr(t, "name", "") or (t if isinstance(t, str) else "") or "").strip()
        if not name:
            continue
        catalog.append({
            "name": name,
            "description": str(getattr(t, "description", "") or "")[:400],
        })
    return catalog


# ── P2 占位（另刀；本 tip 不实现拟议包/钩子/观察模式 Gate）──────

P2_PROPOSAL_STUB: dict[str, str] = {
    "status": "not_implemented",
    "message": "无匹配工具：可转人工/派开发；拟议 patch 下期（不自动改产）",
}


def format_no_match_reply() -> str:
    """无候选时的自然语言回复模板（引用 P2 占位句；不写仓库、不建 PR）。"""
    return (
        "这个需求我当前没有可直接执行的已授权工具，先不硬做。"
        f"{P2_PROPOSAL_STUB['message']}。"
        "你可以选择转人工或派开发跟进，也可以换个说法再试一次。"
    )
