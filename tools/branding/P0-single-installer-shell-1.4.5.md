# P0 单安装包统一壳（主窗工作台 + 运营悬浮）（1.4.5）

日期：2026-11-07（Asia/Shanghai）
树：`evoflow-ops-1.4.0` / 分支 `brand/1.4.0-pathC` → bump **1.4.5**（基线 `98fc296`）
拍板：单安装包统一壳——主窗冷启 = 工作台首页；运营台走 always-on-top 悬浮窗；托盘留浏览器应急通道；`evoflow://` 辅注册。

## 做了什么

| 能力 | 落点 |
|------|------|
| 工作台常量 | `evopanel/src/lib/workbench-urls.js`：`WORKBENCH_HOME_URL` / `OPS_BOARD_URL`（线上域名，禁回退本机端口） |
| 主窗冷启 = 工作台首页 | 新增 `/workbench-home` 路由（`src/pages/workbench-home.js`）承载 `WORKBENCH_HOME_URL`；`main.js` 默认路由 → `/workbench-home`。主窗 label 仍 `main`，不 `main.hide()`，不拆 Gateway / panel-login |
| 运营悬浮窗 | `commands/workbench_shell.rs`：label=`ops-float`，`WebviewUrl::App("index.html#/chat")` 加载本机运营 shell（chat + shell-aside），`.always_on_top(true)`；进运营后主窗不藏 |
| 托盘「打开运营」 | `tray.rs` → `workbench_shell_open_ops_float` |
| 托盘「在浏览器打开工作台」 | `tray.rs` → `workbench_shell_open_in_browser`：`tauri_plugin_shell` 的 `open` 打开 `WORKBENCH_HOME_URL`（应急通道） |
| `evoflow://` 深链辅注册 | macOS：`src-tauri/Info.plist` 注册 `evoflow` scheme（Tauri 合并进生成 plist）；Windows 只留 `handle_deep_link` 代码路径，不打包 |

## 红线（测例钉死）

1. 不回退 1.4.4 确认派单 / 跟单：`ui-extension-shell.js` 待确认条 + `WorkbenchOrderDraftCard` 原样保留
2. 草稿永不自动 dispatch；只有人点「确认派单」才 `_authed_post("/api/opsboard/dispatch")`
3. 禁真调工作台 dispatch（除非 mock）；禁回退 1.4.4 能力
4. 生产工单 iframe 继续走现有 `ecom-ops-board`，不重装扩展
5. 主窗 label 保持 `main`；禁止 `main.hide()`；勿拆 Gateway / panel-login
6. 无关脏文件先 `git checkout --` 还原；保留已有 `workbench-urls.js`
7. 不打 Win setup / 不打本刀 Mac DMG；不动 evoflow-fork / 生产热文件 / #7

## 验收清单

- [ ] 冷启主窗 = 工作台首页（`WORKBENCH_HOME_URL`）
- [ ] 悬浮运营可用（always-on-top）且主窗仍在（不隐藏）
- [ ] 生产工单 iframe + 确认派单未回退（`test_opsboard_confirm_routes.py` PASS）
- [ ] 托盘「在浏览器打开工作台」应急可用
- [ ] `evoflow://` 深链已注册（macOS Info.plist）
- [ ] VERSION = 1.4.5；无 setup.exe
