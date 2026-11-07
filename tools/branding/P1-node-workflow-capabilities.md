# P1 节点级工作流能力（1.4.3）— 验收短注

日期：2026-11-07（Asia/Shanghai）  
树：`evoflow-ops-1.4.0` / 分支 `brand/1.4.0-pathC` → 本刀 bump **1.4.3**

## 摸底结论（相对官方 1.3.4 / 地基 1.3.7）

已在库、可直接用：
- 每步 `skills` / `tools` / `mcp_servers` / `knowledge_vault_ids` / `model` / `thinking_enabled`
- `WorkflowStudioFloat` 悬浮配置、执行壳下拉
- 应用 / 步骤 `project_path`（库列 + 启动 `_ensure_post_baseline_columns` 补列）
- `plan_subtasks_sync` → `worker_profile` 贯通

本刀补上的缺口：
- **节点显式 `tools` 挂 `workbench_*` 时，必须与执行者 AgentConfig.tools 求交**；不得靠画布声明冲开 L2 fail-closed
- 两条真实运营向模板：「套图 → 质检」「套图 → 视频编排」
- 应用卡片元信息展示「工作目录 …」（有值时）

## 两条模板怎么配

1. 工作流页 →「新建工作流 ▾」→「从模板创建」
2. 选 **套图 → 质检** 或 **套图 → 视频编排**
3. 确认员工种子已有 `tuantu-op` / `shipin-op` / `kefu-op`（`ensure_workbench_role_agents`）
4. 打开画布：点节点看右侧悬浮卡——工具 / 思考开关已按模板写好；可再改技能 / MCP / 知识库 / 模型
5. 应用设置里可填「工作目录」；列表卡片会显示截断路径
6. 试跑即可（本刀不要求真跟片 / 真扣费）

## 与白名单分层关系

| 来源 | 非 workbench 工具 | workbench_* |
|------|-------------------|-------------|
| 节点 `tools`（本刀） | 按声明挂载 | ∩ 执行者 AgentConfig.tools，否则剥离 |
| AgentConfig / SubagentConfig | 显式白名单 | 显式白名单 |
| 继承兜底 | 模式目录 | 一律剥离 |

`draft_workbench_order` 仍只出草稿；部门群回执口径不变。

## 本刀不做

Windows 包；真跟片；关键帧；push；自动覆盖 `/Applications`；updater 仍关。

## 负责人验收

- [ ] 模板「套图 → 质检」：第 1 步有 image 工具；第 2 步无生产 workbench
- [ ] 模板「套图 → 视频编排」：两步分别挂 image / video 子集
- [ ] 画布把套图步的 tools 改成含 `workbench_video_submit` 并保存后跑：执行时仍拿不到视频提交（测例已钉）
- [ ] 旧库启动后 `evoflow_apps.project_path` 可写
- [ ] 安装 1.4.3 DMG 后 Info.plist=1.4.3，包内 gateway 可执行
