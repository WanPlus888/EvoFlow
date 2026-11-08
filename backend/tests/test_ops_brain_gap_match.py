"""运营大脑缺口匹配（ops_brain_gap_match）纯函数回归（1.4.12 能力扩展）。

覆盖拍板口径 D / 验收 8-12：
- bash / 高危 MCP 永不进候选（即使词典被误改，denylist 双保险拦截）；
- 只读 web_search → RISK_AUTO 可直接跑（执行前调研）；
- 无候选 → P2 占位文案（本 tip 仅 stub，不自动改产）；
- OPS_BRAIN_GAP_MATCH=0 → 匹配恒空（总开关/回滚兜底）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(_BACKEND_ROOT / "packages" / "harness"))

from evoflow.agents.middlewares.ops_brain_gap_match_middleware import build_gap_match_block  # noqa: E402
from evoflow.collab import ops_brain_gap_match as gm  # noqa: E402
from evoflow.collab.ops_brain_gap_match import (  # noqa: E402
    GAP_MATCH_DENYLIST,
    P2_PROPOSAL_STUB,
    build_catalog_from_tools,
    format_no_match_reply,
    gap_match_enabled,
    is_high_risk_mcp,
    match_registered_tools,
)


def _catalog(*names: str) -> list[dict]:
    return [{"name": n, "description": ""} for n in names]


def _allowed(*names: str) -> set[str]:
    return set(names)


# ── 1) 总开关 ─────────────────────────────────────────────────


def test_gap_match_enabled_default_on_and_env_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPS_BRAIN_GAP_MATCH", raising=False)
    assert gap_match_enabled() is True
    for off in ("0", "false", "no", "off"):
        monkeypatch.setenv("OPS_BRAIN_GAP_MATCH", off)
        assert gap_match_enabled() is False


def test_disabled_switch_returns_empty_even_with_obvious_match(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPS_BRAIN_GAP_MATCH", "0")
    out = match_registered_tools(
        intent_text="帮我联网搜一下最新热门趋势",
        allowed_tools=_allowed("web_search"),
        catalog=_catalog("web_search"),
    )
    assert out == []


# ── 2) 白名单 / 目录双门 ───────────────────────────────────────


def test_only_tools_inside_allowed_and_catalog_match():
    out = match_registered_tools(
        intent_text="联网搜一下竞品",
        allowed_tools=_allowed("web_search"),
        catalog=_catalog("web_search"),
    )
    assert [m.tool_name for m in out] == ["web_search"]

    # 不在 allowed（AgentConfig 未勾选 / 会话门禁剥离）→ 不候选
    out2 = match_registered_tools(
        intent_text="联网搜一下竞品",
        allowed_tools=_allowed("read"),
        catalog=_catalog("web_search"),
    )
    assert out2 == []

    # 未注册（catalog 缺席）→ 不候选
    out3 = match_registered_tools(
        intent_text="联网搜一下竞品",
        allowed_tools=_allowed("web_search"),
        catalog=_catalog("read"),
    )
    assert out3 == []


def test_empty_intent_returns_empty():
    assert match_registered_tools(
        intent_text="   ",
        allowed_tools=_allowed("web_search"),
        catalog=_catalog("web_search"),
    ) == []


# ── 3) 拍板 D：bash / 高危 MCP 硬排除 ──────────────────────────


def test_denylist_tools_never_candidates_even_if_lexicon_added(monkeypatch: pytest.MonkeyPatch):
    """即使词典被误改成 bash 可命中，denylist 仍硬拦截（双保险）。"""
    poisoned = dict(gm._GAP_INTENT_LEXICON)
    for name in ("bash", "terminal", "process", "taskstop", "delete"):
        poisoned[name] = ("跑命令", "执行")
    monkeypatch.setattr(gm, "_GAP_INTENT_LEXICON", poisoned)

    out = match_registered_tools(
        intent_text="帮我跑命令执行删除",
        allowed_tools=_allowed("bash", "terminal", "process", "taskstop", "delete", "web_search"),
        catalog=_catalog("bash", "terminal", "process", "taskstop", "delete", "web_search"),
    )
    names = [m.tool_name for m in out]
    assert "bash" not in names
    assert "terminal" not in names
    assert "process" not in names
    assert "taskstop" not in names
    assert "delete" not in names


def test_denylist_contains_shell_family():
    assert GAP_MATCH_DENYLIST >= {"bash", "process", "taskstop", "delete"}


def test_high_risk_mcp_excluded_and_readonly_allowed(monkeypatch: pytest.MonkeyPatch):
    # node_repl 内核：confirm 级 → 高危
    assert is_high_risk_mcp("mcp__node_repl__js") is True
    # 无 annotations 的外部 MCP：兜底 session → 高危
    monkeypatch.delenv("EVOFLOW_MCP_AUTO_TOOLS", raising=False)
    assert is_high_risk_mcp("mcp__unknown_srv__write_thing") is True
    # 非 MCP 名 → False
    assert is_high_risk_mcp("web_search") is False

    # readOnlyHint → auto 的只读 MCP 不排除；但候选仍须在 allowed + catalog 内
    monkeypatch.setattr(
        "evoflow.mcp.annotations.get_tool_hints",
        lambda name: {"readOnlyHint": True},
    )
    assert is_high_risk_mcp("mcp__docs__search") is False

    poisoned = dict(gm._GAP_INTENT_LEXICON)
    poisoned["mcp__docs__search"] = ("联网搜",)
    monkeypatch.setattr(gm, "_GAP_INTENT_LEXICON", poisoned)
    out = match_registered_tools(
        intent_text="联网搜一下文档",
        allowed_tools=_allowed("mcp__docs__search", "mcp__node_repl__js", "mcp__unknown_srv__write_thing"),
        catalog=_catalog("mcp__docs__search", "mcp__node_repl__js", "mcp__unknown_srv__write_thing"),
    )
    names = [m.tool_name for m in out]
    assert "mcp__docs__search" in names
    assert "mcp__node_repl__js" not in names
    assert "mcp__unknown_srv__write_thing" not in names


# ── 4) 风险标注（展示用；执行闸在 tool_approval）────────────────


def test_web_search_is_auto_research():
    out = match_registered_tools(
        intent_text="联网查一下最新热门趋势",
        allowed_tools=_allowed("web_search", "fetch_url"),
        catalog=_catalog("web_search", "fetch_url"),
    )
    assert out and out[0].tool_name == "web_search"
    assert out[0].risk == "auto"


def test_workbench_submits_match_with_confirm_risk():
    out = match_registered_tools(
        intent_text="给这个商品提交主图，再提交一个短视频任务",
        allowed_tools=_allowed("workbench_image_submit", "workbench_video_submit", "workbench_products_list"),
        catalog=_catalog("workbench_image_submit", "workbench_video_submit", "workbench_products_list"),
    )
    names = [m.tool_name for m in out]
    assert "workbench_image_submit" in names
    assert "workbench_video_submit" in names
    for m in out:
        if m.tool_name in ("workbench_image_submit", "workbench_video_submit"):
            assert m.risk == "confirm"
            assert m.reason and len(m.reason) <= 200


# ── 5) 排序 / 截断 / 确定性 ────────────────────────────────────


def test_max_candidates_cap(monkeypatch: pytest.MonkeyPatch):
    poisoned = {name: ("联网搜",) for name in ("web_search", "fetch_url", "knowledge", "workbench_products_list")}
    monkeypatch.setattr(gm, "_GAP_INTENT_LEXICON", poisoned)
    out = match_registered_tools(
        intent_text="联网搜",
        allowed_tools=_allowed(*poisoned),
        catalog=_catalog(*poisoned),
        max_candidates=2,
    )
    assert len(out) == 2


def test_deterministic_output():
    kwargs = dict(
        intent_text="联网搜一下然后提交主图",
        allowed_tools=_allowed("web_search", "workbench_image_submit"),
        catalog=_catalog("web_search", "workbench_image_submit"),
    )
    a = match_registered_tools(**kwargs)
    b = match_registered_tools(**kwargs)
    assert a == b


# ── 6) 无匹配 → P2 占位（验收 11：仓库 tip 不变，不自动改产）────


def test_no_match_returns_empty_and_p2_stub():
    out = match_registered_tools(
        intent_text="今天天气不错",
        allowed_tools=_allowed("web_search"),
        catalog=_catalog("web_search"),
    )
    assert out == []
    assert P2_PROPOSAL_STUB["status"] == "not_implemented"
    assert "不自动改产" in P2_PROPOSAL_STUB["message"]
    reply = format_no_match_reply()
    assert P2_PROPOSAL_STUB["message"] in reply
    assert "转人工" in reply


# ── 7) 目录构建 helper ────────────────────────────────────────


def test_build_catalog_from_tools():
    class _FakeTool:
        name = "web_search"
        description = "联网搜索"

    catalog = build_catalog_from_tools([_FakeTool(), "read", None])
    assert catalog == [
        {"name": "web_search", "description": "联网搜索"},
        {"name": "read", "description": ""},
    ]


# ── 8) 中间件提示块（意图→候选旁路，只读注入）──────────────────


def test_build_gap_match_block_lists_candidates_and_rules():
    tools = [
        type("T", (), {"name": n, "description": ""})()
        for n in ("web_search", "workbench_image_submit", "bash")
    ]
    block = build_gap_match_block(
        intent_text="联网搜一下参考，然后给商品提交主图",
        allowed_tools={"web_search", "workbench_image_submit", "bash"},
        tools_for_catalog=tools,
    )
    assert block.startswith("<ops_brain_gap_match>")
    assert "web_search" in block
    assert "workbench_image_submit" in block
    assert "- bash" not in block  # denylist 工具不进候选行（规则句提及不算）
    assert "确认卡" in block  # 执行闸规则说明


def test_build_gap_match_block_empty_when_no_candidates():
    assert (
        build_gap_match_block(
            intent_text="今天天气不错",
            allowed_tools={"web_search"},
            tools_for_catalog=[type("T", (), {"name": "web_search", "description": ""})()],
        )
        == ""
    )


def test_middleware_injects_named_tail_message(monkeypatch: pytest.MonkeyPatch):
    """真实 wrap_model_call：用户回合末尾注入命名消息；开关关闭则原样透传。"""
    from langchain_core.messages import AIMessage, HumanMessage

    from evoflow.agents.middlewares.ops_brain_gap_match_middleware import OpsBrainGapMatchMiddleware

    class _FakeRequest:
        def __init__(self, messages, tools):
            self.messages = list(messages)
            self.state = {"messages": list(messages)}
            self.tools = list(tools)
            self.runtime = None
            self.system_message = None

        def override(self, **kw):
            clone = _FakeRequest(kw.get("messages", self.messages), self.tools)
            clone.state = self.state
            clone.runtime = self.runtime
            clone.system_message = kw.get("system_message", self.system_message)
            return clone

    user_turn = [HumanMessage(content="帮我联网搜一下最新热门趋势，参考完提交主图")]
    tools = [
        type("T", (), {"name": n, "description": ""})()
        for n in ("web_search", "workbench_image_submit", "bash", "read")
    ]
    mw = OpsBrainGapMatchMiddleware()
    seen: dict = {}

    def handler(request):
        seen["messages"] = list(request.messages)
        return "ok"

    monkeypatch.delenv("OPS_BRAIN_GAP_MATCH", raising=False)
    result = mw.wrap_model_call(_FakeRequest(user_turn, tools), handler)
    assert result == "ok"
    injected = [m for m in seen["messages"] if getattr(m, "name", None) == "ops_brain_gap_match"]
    assert len(injected) == 1
    assert "web_search" in injected[0].content
    assert "- bash" not in injected[0].content  # denylist 不进候选行
    # 原用户消息保留在前
    assert seen["messages"][0] is user_turn[0]

    # 工具循环续轮（末尾是 AI/Tool 消息）→ 不注入
    tool_loop = [*user_turn, AIMessage(content="好的"), HumanMessage(content="", name="tool")]
    seen.clear()
    mw.wrap_model_call(_FakeRequest(tool_loop, tools), handler)
    assert not [m for m in seen["messages"] if getattr(m, "name", None) == "ops_brain_gap_match"]

    # 总开关关闭 → 原样透传
    monkeypatch.setenv("OPS_BRAIN_GAP_MATCH", "0")
    seen.clear()
    mw.wrap_model_call(_FakeRequest(user_turn, tools), handler)
    assert not [m for m in seen["messages"] if getattr(m, "name", None) == "ops_brain_gap_match"]
    assert seen["messages"] == user_turn

    # 内部异常 fail-open：handler 仍被调用（不崩 run）
    class _BadRequest(_FakeRequest):
        @property
        def tools(self):
            raise RuntimeError("boom")  # 中间件会碰 tools；测试 handler 不碰

        @tools.setter
        def tools(self, value):
            self._t = value

    monkeypatch.delenv("OPS_BRAIN_GAP_MATCH", raising=False)
    assert mw.wrap_model_call(_BadRequest(user_turn, tools), handler) == "ok"
