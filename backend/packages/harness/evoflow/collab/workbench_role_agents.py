"""套图岗 / 视频岗员工配置种子（阶段1收口 + P1 能力边界协同）。

把工作台岗位写进 ``evoflow_agents``（SQLite），让已验收的白名单门禁
（``WORKBENCH_TOOL_NAMES`` / ``_drop_workbench_tools`` / ``_gate_workbench_tools_for_session``）
能在真实 ``load_agent_config`` 路径上解析到岗位工具集；并写入 ``platform_scope``
（L1 平台域 ACL），与 L2 工作台岗位子集分层叠加。

设计要点：
- 本模块 **import 无副作用**：只声明常量与函数，写库动作由调用方触发
  （``ensure_workbench_role_agents``，或 ``__main__`` 手工入口）。
- 幂等：已有 agent 覆盖 ``agent_name`` / ``tools`` / ``agent_type`` / ``platform_scope``，
  其它字段（description / model / skills / mcp / tags…）原样保留；不碰无关 agent。
- ``tools`` 顺序为 ``BASE_TOOLS + ROLE_RESEARCH_TOOLS(生产两岗) + 岗位工作台工具``，去重保序。
- ``draft_workbench_order`` 在 BASE_TOOLS（三岗可见），但不在 ``WORKBENCH_TOOL_NAMES``。
- 挂搜（1.4.12）：``web_search`` / ``fetch_url`` 为只读调研（RISK_AUTO），不属
  ``WORKBENCH_TOOL_NAMES``，不走岗位工作台门禁；两 submit 另由 TOOL_RISK_LEVELS
  的 RISK_CONFIRM 确认卡闸住（fail-closed 不变）。
"""

from __future__ import annotations

from typing import Any

# 岗位 agent code（hyphen-case，符合 AGENT_NAME_PATTERN）
TUANTU_OP = "tuantu-op"
SHIPIN_OP = "shipin-op"
KEFU_OP = "kefu-op"  # 可选对照岗：无任何 workbench_ 工具

# 草稿工具：三岗均可见；不在 WORKBENCH_TOOL_NAMES；只出草稿不派单不扣费。
DRAFT_WORKBENCH_ORDER_TOOL = "draft_workbench_order"

# 基础工作工具（所有岗位共用；含草稿，不含 workbench_* 生产工具）
BASE_TOOLS: list[str] = ["read", "bash", "todo", "view_image", DRAFT_WORKBENCH_ORDER_TOOL]

# 岗位挂网搜（运营大脑 1.4.12 能力扩展 · 口径B）：套图/视频岗显式追加只读调研工具，
# 供执行前外网调研（RISK_AUTO，直接跑）；客服对照岗本刀不挂（保持 BASE）。
ROLE_RESEARCH_TOOLS: list[str] = ["web_search", "fetch_url"]

# 岗位专属工作台工具（与 WORKBENCH_TOOL_NAMES 子集一致）
IMAGE_WORKBENCH_TOOLS: list[str] = [
    "workbench_products_list",
    "workbench_image_submit",
    "workbench_image_status",
]
VIDEO_WORKBENCH_TOOLS: list[str] = [
    "workbench_products_list",
    "workbench_video_options",
    "workbench_video_submit",
    "workbench_video_status",
]

# L1 平台域 ACL 种子（与 L2 tools 子集叠加；不设限不会放开 workbench_*）
# 套图/视频：自定义 knowledge 可写；客服：平台动作全禁。
ROLE_PLATFORM_SCOPES: dict[str, dict] = {
    TUANTU_OP: {"mode": "custom", "domains": ["knowledge"], "actions": [], "max_risk": "write"},
    SHIPIN_OP: {"mode": "custom", "domains": ["knowledge"], "actions": [], "max_risk": "write"},
    KEFU_OP: {"mode": "none", "domains": [], "actions": [], "max_risk": "write"},
}

# (code, agent_name, 岗位工作台工具, description, 是否挂只读调研工具)
# 生产两岗（套图/视频）挂 ROLE_RESEARCH_TOOLS；客服对照岗不挂（拍板口径B）。
# 1.4.11 档案参考图自动优选 + 1.4.12 挂搜/确认：描述合并两边意图。
_ROLE_SPECS: tuple[tuple[str, str, list[str], str, bool], ...] = (
    (
        TUANTU_OP,
        "套图岗",
        IMAGE_WORKBENCH_TOOLS,
        "工作台套图岗：查商品档案、提交并跟踪单图生成。生产前必须 workbench_products_list "
        "确认商品；省略 image_indexes 由服务端自动优选参考图，提交后用返回的 "
        "selected_indexes/select_layer/select_reason 回显「已选 #n（理由）」；"
        "用户说「用第 n 张」时显式传 [n] 覆盖，禁止再自动改掉。"
        "可只读检索外网；真正 submit 前会弹确认卡。",
        True,
    ),
    (
        SHIPIN_OP,
        "视频岗",
        VIDEO_WORKBENCH_TOOLS,
        "工作台视频岗：查商品档案与供应商能力、提交并跟踪短视频任务。生产前必须 "
        "workbench_products_list 确认商品；省略 image_indexes 由服务端自动优选"
        "（异视角优先），提交后回显 selected_indexes/select_layer/select_reason；"
        "用户指定下标时显式传入覆盖，禁止再自动改掉。"
        "可只读检索外网；真正 submit 前会弹确认卡。",
        True,
    ),
    (KEFU_OP, "客服岗", [], "客服岗（对照）：只用基础工具（含草稿），不接触工作台生产工具。", False),
)


def _dedupe_preserve_order(names: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        n = str(raw or "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _role_tools(role_workbench_tools: list[str], *, include_research: bool = False) -> list[str]:
    research = ROLE_RESEARCH_TOOLS if include_research else []
    return _dedupe_preserve_order([*BASE_TOOLS, *research, *role_workbench_tools])


def ensure_workbench_role_agents(*, include_kefu: bool = True) -> dict[str, list[str]]:
    """写入（或刷新）套图岗 / 视频岗（/ 客服岗）员工配置。

    对每个目标 agent：

    a. 尝试 ``load_agent_config(code)``；若存在，用 ``cfg.model_dump(mode="python")``
       得到 dict，再覆盖 ``agent_name`` / ``tools`` / ``agent_type="custom"`` /
       ``platform_scope``（L1），其它字段保持；
    b. 若不存在，新建最小 dict；
       c. ``tools`` 为 ``BASE_TOOLS (+ ROLE_RESEARCH_TOOLS 生产两岗) + 岗位工作台工具``（去重保序）；
    d. 调用 ``save_agent_config(code, payload)``；
    e. 若存在 ``invalidate_agent_config_cache``，保存后调用它（下一轮生效）。

    幂等：重复调用不报错；不删除其它 agent；不清空无关字段。
    返回 ``{agent_code: tools 列表}`` 便于测例断言。
    """
    from evoflow.config.agents_config import (
        load_agent_config,
        save_agent_config,
    )

    try:
        from evoflow.config.agents_config import invalidate_agent_config_cache
    except ImportError:  # pragma: no cover - 仓库当前版本一定有；防御旧布局
        invalidate_agent_config_cache = None  # type: ignore[assignment]

    out: dict[str, list[str]] = {}
    for code, agent_name, role_tools, description, include_research in _ROLE_SPECS:
        if code == KEFU_OP and not include_kefu:
            continue
        tools = _role_tools(role_tools, include_research=include_research)
        payload: dict[str, Any]
        try:
            cfg = load_agent_config(code)
        except (FileNotFoundError, ValueError):
            cfg = None
        if cfg is not None:
            payload = cfg.model_dump(mode="python", exclude={"name"})
        else:
            payload = {"agent_code": code, "description": description}
        payload["agent_code"] = code
        payload["agent_name"] = agent_name
        payload["agent_type"] = "custom"
        payload["tools"] = list(tools)
        # L1：品牌托管三岗写死 platform_scope，与 L2 tools 子集协同表达岗位。
        payload["platform_scope"] = dict(ROLE_PLATFORM_SCOPES[code])
        save_agent_config(code, payload)
        if invalidate_agent_config_cache is not None:
            invalidate_agent_config_cache(code)
        out[code] = list(tools)
    return out


if __name__ == "__main__":
    print(ensure_workbench_role_agents())
