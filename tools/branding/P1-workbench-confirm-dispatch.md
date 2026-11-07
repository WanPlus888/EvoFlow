# P0+P1 终端×工作台：确认派单 + 跟单验收（1.4.4）

日期：2026-11-07（Asia/Shanghai）  
树：`evoflow-ops-1.4.0` / 分支 `brand/1.4.0-pathC` → bump **1.4.4**  
拍板：路径 B 深嵌工单台 UI；聊天 + 生产工单页双入口确认；P0+P1 同刀。

## 做了什么

| 能力 | 落点 |
|------|------|
| 深嵌工单台 | 一级导航「生产工单」→ `/extensions/ecom-ops-board` iframe（SSO vault 免反复登）；扩展壳顶部注入「待确认派单」条 |
| 聊天确认派单 | `draft_workbench_order` 工具结果下挂 `WorkbenchOrderDraftCard` → `POST /api/opsboard/drafts/{ref}/confirm` |
| 工单页确认派单 | 扩展壳草稿条 + 驾驶舱 `OpsOrderSummary` 待确认列表，同一 confirm API |
| 跟单 | `GET /api/opsboard/orders/by-ref/{ref}` |
| 验收 | `POST /api/opsboard/orders/{id}/approve\|reject`（人点） |

## 红线（测例钉死）

1. `draft_workbench_order` **永不**自动 HTTP 派单/扣费（只解析 + 本地落草稿）
2. 只有人点「确认派单」才 `_authed_post("/api/opsboard/dispatch")`
3. 同 `external_ref` 二次确认 `deduped=true`，不再次 dispatch
4. 部门群回执口径不变（≠ 扣费派单）
5. fail-closed 岗位白名单不动；未点名新生产能力不加
6. 不改/不整推工作台生产热文件；Windows 不做；#7 勿合

## 验收清单

- [ ] 聊天出草稿卡 → 未点确认时网关/工作台无 dispatch 调用
- [ ] 聊天点确认 / 生产工单页点确认 → 各能派成；同号第二次不双扣
- [ ] 按工单号查得到关联记录；通过/打回可点
- [ ] iframe 工单台仍可用（vault 登录态）
- [ ] 相关 pytest + vitest PASS；DMG Info.plist=1.4.4，包内 gateway 可执行
