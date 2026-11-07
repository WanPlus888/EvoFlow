# P1 能力边界协同（1.4.1）— 冲突分析与负责人短注

日期：2026-11-07（Asia/Shanghai）  
树：`evoflow-ops-1.4.0` / 分支 `brand/1.4.0-pathC` → 本刀 bump **1.4.1**

## 两层各管什么（不要混）

| 层 | 配置字段 | 管什么 | 默认 |
|----|----------|--------|------|
| **L1 平台域 ACL** | `AgentConfig.platform_scope`（extra_json） | `platform` 工具里的域/动作（knowledge / media / …） | `None` = **不设限**（存量） |
| **L2 工作台岗位子集** | `AgentConfig.tools` ∩ `WORKBENCH_TOOL_NAMES` | 仅 `workbench_*` 生产工具 | **fail-closed**：未显式勾选一律剥离 |

官方 1.3.2「员工平台能力清单」= L1。  
我们三岗白名单（套图 / 视频 / 客服）= L2。

## 冲突点与结论

1. **「不设限」会不会冲掉工作台 fail-closed？**  
   不会，也不允许。L1 只过滤 platform 动作；L2 门禁在 `_gate_workbench_tools_for_session` / `_drop_workbench_tools`，与 `platform_scope` 无关。本刀补分层回归测例钉死。

2. **自定义能力如何表达三岗？**  
   - 套图：`tools` ⊇ 套图 workbench 子集；`platform_scope` 建议 custom（如 knowledge，上限 write），**不**靠 platform media 代替套图工具。  
   - 视频：同理，视频 workbench 子集。  
   - 客服：`tools` 无任何 `workbench_*`；`platform_scope=mode:none`（平台动作全拒）。  
   种子 `ensure_workbench_role_agents` 写齐两层；UI 四态（不设限 / 全量+风险上限 / 全禁 / 自定义）可改。

3. **草稿工具 `draft_workbench_order`**  
   - **不在** `WORKBENCH_TOOL_NAMES`（不是生产提交工具）。  
   - 策略：三岗 `BASE_TOOLS` 均可见（含客服），便于收口诉求；**仍只出草稿，不派单不扣费**。  
   - 可见性跟 L2 生产门禁解耦：有草稿 ≠ 有 submit。

4. **改能力后何时生效？**  
   `save_agent_config` → `invalidate_agent_config_cache`（并清 tool-names / 动态提示词缓存）；跨进程靠 `probe_agent_capability_revision`。与现网路径去重，不另开通道。

## 本刀不做

部门群派工条 / 节点级工作流画布 / Windows 包 / 自动覆盖 `/Applications` / push 公仓。

## 负责人验收清单

- [ ] 智能体编辑：平台能力四态可保存，下一轮对话生效  
- [ ] 套图岗调 `workbench_video_submit` 被拒；客服无生产 workbench  
- [ ] 平台「不设限」的岗，若未勾选 workbench，仍拿不到生产工具  
- [ ] 任意岗调草稿工具只出 draft JSON，不派单不扣费  
- [ ] 安装 1.4.1 DMG 后 Info.plist=1.4.1，包内 gateway 可执行  
