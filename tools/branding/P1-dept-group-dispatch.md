# P1 部门群派工条 + 自动回执（1.4.2）

日期：2026-11-07（Asia/Shanghai）  
树：`evoflow-ops-1.4.0` / 分支 `brand/1.4.0-pathC` → bump **1.4.2**

## 官方能力来源

| 能力 | 官方版 | 本树位置 |
|------|--------|----------|
| 派工条 | 1.3.2 | `dept-group-dispatch-status.ts` + `HomeDeptGroupChat` `MentionDispatchStrip` |
| 自动回执 | 1.3.7 | `proactive/dept_group_receipt.py` ← `update_run_status` / `save_task_bundle` |

1.4.0 Path C 已带入代码；本刀做**验收接线 + 品牌边界**，不是从零实现。

## 本刀改动

1. **前端徽标**：`auto_receipt` / `dept-receipt-*` → 「自动回执」chip；气泡左边线提示
2. **开群轮询**：5s 合并远程新消息（只追加缺 id；不覆盖本地流式）
3. **文案边界**：回执正文与 `<dept_group_im>` 规则 7 写明 ≠ 工作台扣费派单；draft 仍只草稿
4. **驾驶舱**：`OpsOrderSummary` 脚注区分口径

## 两套「派工」不要混

| | 部门群派工条 / 回执 | 驾驶舱生产工单 |
|--|-------------------|----------------|
| 数据源 | 叫醒队列 + 群时间线 / run 终态 | `/opsboard/summary` 工作台 |
| 含义 | @ 谁、答没答、任务结果通报 | 待验收 / 生产中 / 花费（扣费） |
| 扣费 | **不扣费** | **扣费派单口径** |
| 草稿工具 | 无关；`draft_workbench_order` 只出 draft JSON | 确认后由工单台派单 |

## 本刀不做

节点级工作流画布大改 / Windows / 自动覆盖 `/Applications` / push / 真跟片跟帧。

## 验收清单

- [ ] 部门群 @ 后气泡下可见排队中→回答中→已回（或失败）
- [ ] 员工起后台任务完成后，群里出现「自动回执」气泡（开着群不需重进）
- [ ] 回执文案含「非工作台扣费派单」；徽标 title 一致
- [ ] 驾驶舱生产工单脚注可见；与派工条不重复计数
- [ ] `draft_workbench_order` 仍只草稿
- [ ] 相关测例 PASS；DMG Info.plist=1.4.2，包内 gateway 可执行
