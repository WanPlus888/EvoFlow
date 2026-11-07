//! 单安装包统一壳 1.4.5：工作台首页 / 运营悬浮窗 / 浏览器应急入口
//!
//! - 主窗冷启 = 工作台首页（见 `lib.rs` 里 main 窗口 URL）。
//! - `ops-float`：次级 WebviewWindow，加载本机运营 shell（chat + shell-aside），
//!   always-on-top 悬浮；进运营后主窗不隐藏。
//! - 托盘「在浏览器打开工作台」：用 `tauri_plugin_shell` 的 `open` 打开
//!   `WORKBENCH_HOME_URL`（外部浏览器，应急通道）。
//!
//! 常量来源：`evopanel/src/lib/workbench-urls.js`（前端同源）。Rust 侧镜像一份，
//! 避免跨语言 import；两处 URL 必须一致（发版校验见 tools/branding）。

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow};

/// 工作台首页（外链 Web）。与 `workbench-urls.js` 的 `WORKBENCH_HOME_URL` 一致。
pub const WORKBENCH_HOME_URL: &str = "https://workbench.kll666.cn/";

/// 运营悬浮窗 label。
pub const OPS_FLOAT_LABEL: &str = "ops-float";

/// 运营悬浮窗初始尺寸（逻辑像素）与右上角边距。
const OPS_FLOAT_WIDTH: f64 = 520.0;
const OPS_FLOAT_HEIGHT: f64 = 780.0;
const OPS_FLOAT_MARGIN: f64 = 24.0;

/// 打开 / 聚焦运营悬浮窗（always-on-top）。不隐藏主窗。
///
/// 窗口加载本机运营 shell 的聊天首页（chat + shell-aside）。生产工单仍走
/// shell-aside 现有 `ecom-ops-board`，不在此重装扩展。
#[tauri::command]
pub async fn workbench_shell_open_ops_float(app: AppHandle) -> Result<(), String> {
    // WebviewWindowBuilder::build() 不能跑在 async 命令的运行时上（与
    // voice_overlay / browser_embed 同一规则），挪到阻塞线程执行。
    let app_create = app.clone();
    tauri::async_runtime::spawn_blocking(move || ensure_ops_float_window(&app_create))
        .await
        .map_err(|e| format!("ops-float create join failed: {e}"))??;

    if let Some(win) = app.get_webview_window(OPS_FLOAT_LABEL) {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
    Ok(())
}

/// 隐藏运营悬浮窗（保留实例，便于快速恢复）。
#[tauri::command]
pub async fn workbench_shell_hide_ops_float(app: AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window(OPS_FLOAT_LABEL) {
        let _ = win.hide();
    }
    Ok(())
}

/// 用系统默认浏览器打开工作台首页（`tauri_plugin_shell` 的 `open`）。
#[tauri::command]
pub fn workbench_shell_open_in_browser(app: AppHandle) -> Result<(), String> {
    open_workbench_in_browser(&app)
}

/// 确保存在运营悬浮窗；已存在则复用并重新置顶。
fn ensure_ops_float_window(app: &AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window(OPS_FLOAT_LABEL) {
        let _ = win.set_always_on_top(true);
        return Ok(());
    }

    let pos = ops_float_position(app)?;
    let win = build_ops_float_window(app, pos)?;
    let _ = win.set_always_on_top(true);
    Ok(())
}

fn build_ops_float_window(
    app: &AppHandle,
    pos: (f64, f64),
) -> Result<WebviewWindow, String> {
    // 加载本机运营 shell 的聊天首页（chat + shell-aside，含生产工单入口）。
    WebviewWindow::builder(
        app,
        OPS_FLOAT_LABEL,
        WebviewUrl::App("index.html#/chat".into()),
    )
    .title("电商运营 · 运营台")
    .inner_size(OPS_FLOAT_WIDTH, OPS_FLOAT_HEIGHT)
    .position(pos.0, pos.1)
    .decorations(true)
    .resizable(true)
    .always_on_top(true)
    .focused(true)
    .skip_taskbar(false)
    .visible(true)
    .build()
    .map_err(|e| format!("创建运营悬浮窗失败: {e}"))
}

/// 悬浮窗定位到主显示器右上角（逻辑像素）。
fn ops_float_position(app: &AppHandle) -> Result<(f64, f64), String> {
    let monitor = app
        .primary_monitor()
        .map_err(|e| format!("获取显示器信息失败: {e}"))?
        .ok_or_else(|| "无法获取主显示器".to_string())?;
    let scale = monitor.scale_factor().max(1.0);
    let mon_pos = monitor.position();
    let size = monitor.size();

    let logical_w = size.width as f64 / scale;
    let origin_x = mon_pos.x as f64 / scale;
    let origin_y = mon_pos.y as f64 / scale;

    let x = origin_x + logical_w - OPS_FLOAT_WIDTH - OPS_FLOAT_MARGIN;
    let y = origin_y + OPS_FLOAT_MARGIN;
    Ok((x.max(origin_x), y.max(origin_y)))
}

/// 用 `tauri_plugin_shell` 的 `open` 打开工作台首页（外部浏览器应急通道）。
pub fn open_workbench_in_browser(app: &AppHandle) -> Result<(), String> {
    use tauri_plugin_shell::ShellExt;
    app.shell()
        .open(WORKBENCH_HOME_URL, None)
        .map_err(|e| format!("打开工作台失败: {e}"))
}

/// `evoflow://` 深链落点：聚焦主窗并回到工作台首页（辅注册，不接管主路由）。
/// macOS Info.plist 注册 scheme；Windows 只留代码路径不打包。
#[allow(dead_code)]
pub fn handle_deep_link(app: &AppHandle, url: &str) {
    eprintln!("[workbench-shell] deep-link: {url}");
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.unminimize();
        let _ = main.set_focus();
    }
}
