/**
 * 工作台首页（单安装包统一壳 1.4.5）
 *
 * 主窗冷启默认落这里：把线上工作台首页 `WORKBENCH_HOME_URL` 全幅嵌进来，
 * 作为「工作台首页」。本机运营 shell（chat + shell-aside / 生产工单）仍在
 * 侧栏与路由里，不回退 1.4.4 确认派单 / 跟单能力。
 *
 * 用 iframe 承载外链（WebviewUrl::External 的等价前端呈现），避免另起原生
 * WebView 抢占主窗 HWND。需要原生外链 Webview 的场景走托盘「在浏览器打开工作台」。
 *
 * 1.4.7：壳侧栏由 router.js 的 evopanel-workbench-mode 藏；本页监听工作台
 * iframe postMessage `{type:'evoflow-ops-brain'}`（兼容 'evopanel-ops-brain'）
 * → navigate('/chat') 切回运营壳（侧栏随之恢复）。
 */
import { WORKBENCH_HOME_URL } from '../lib/workbench-urls.js'

let _onOpsBrainMessage = null

function registerOpsBrainListener(frame) {
  // 防御：render 重入时先注销旧监听
  if (_onOpsBrainMessage) {
    window.removeEventListener('message', _onOpsBrainMessage)
    _onOpsBrainMessage = null
  }
  const onOpsBrainMessage = (ev) => {
    // 仅接受工作台源（线上 origin），或本页 iframe 自身（同源调试）
    const okOrigin = /^https:\/\/workbench\.kll666\.cn(:\d+)?$/.test(ev.origin)
    const fromFrame = frame.contentWindow && ev.source === frame.contentWindow
    if (!fromFrame && !okOrigin) return
    const data = ev.data
    if (!data || typeof data !== 'object') return
    if (data.type !== 'evoflow-ops-brain' && data.type !== 'evopanel-ops-brain') return
    // 切到运营壳：路由离开 workbench-home → setWorkbenchShellMode(false)
    // 1.4.8：打切入标记，chat-return-bar 据此 toast 一次「可点『回工作台』返回」
    try {
      sessionStorage.setItem('ef-from-ops-brain', '1')
    } catch {
      /* 隐私模式等：跳过引导 */
    }
    import('../router.js').then(({ navigate }) => navigate('/chat'))
  }
  window.addEventListener('message', onOpsBrainMessage)
  _onOpsBrainMessage = onOpsBrainMessage
}

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
  frame.dataset.opsBrain = '1'

  page.appendChild(frame)
  registerOpsBrainListener(frame)
  return page
}

export function cleanup() {
  if (_onOpsBrainMessage) {
    window.removeEventListener('message', _onOpsBrainMessage)
    _onOpsBrainMessage = null
  }
  // iframe 随宿主移除自动释放，无需额外动作。
}
