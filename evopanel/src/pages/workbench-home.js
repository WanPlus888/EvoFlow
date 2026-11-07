/**
 * 工作台首页（单安装包统一壳 1.4.5）
 *
 * 主窗冷启默认落这里：把线上工作台首页 `WORKBENCH_HOME_URL` 全幅嵌进来，
 * 作为「工作台首页」。本机运营 shell（chat + shell-aside / 生产工单）仍在
 * 侧栏与路由里，不回退 1.4.4 确认派单 / 跟单能力。
 *
 * 用 iframe 承载外链（WebviewUrl::External 的等价前端呈现），避免另起原生
 * WebView 抢占主窗 HWND。需要原生外链 Webview 的场景走托盘「在浏览器打开工作台」。
 */
import { WORKBENCH_HOME_URL } from '../lib/workbench-urls.js'

export async function render() {
  const page = document.createElement('div')
  page.className = 'workbench-home-host'
  page.setAttribute('data-testid', 'workbench-home')

  const frame = document.createElement('iframe')
  frame.className = 'workbench-home-frame'
  frame.title = '工作台首页'
  frame.src = WORKBENCH_HOME_URL
  frame.setAttribute('referrerpolicy', 'no-referrer-when-downgrade')
  frame.setAttribute('allow', 'clipboard-read; clipboard-write; fullscreen')

  page.appendChild(frame)
  return page
}

export function cleanup() {
  // iframe 随宿主移除自动释放，无需额外动作。
}
