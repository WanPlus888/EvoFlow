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
 *
 * 1.4.10 契约扩展（运营大脑 Bot P0-3，总规划 §6.2）：
 * {
 *   type: 'evoflow-ops-brain',
 *   draft?: { text: string /* ≤2k 纯文本 *\/, urgency?: 'normal'|'urgent',
 *             source?: 'fab'|'main-tab'|'deep-link', clientTs?: number },
 *   ui?: { mode?: 'bot' }
 * }
 * - 无参 ≡ 1.4.9 行为（navigate + ef-from-ops-brain 标记），仅隐式进 bot-mode；
 *   1.4.13 钉死：无参 / 带 draft / ui.mode:'bot' 一律 enterOpsBotMode + /chat
 *   （与「冷启默认 Bot 精简面」同一产品默认，不再回落全壳）；
 * - draft 经 sanitizeOpsBrainDraft 校验（字符串 / 剥 HTML / ≤2k）后只预填输入框
 *   （evopanel_pending_ops_bot_draft → ChatApp apply-pending-ops-bot-draft），
 *   禁止自动 submit / 自动调模型 / 自动扣费 / 自动建单；
 * - urgency 仅作输入旁标签（顶条「加急」徽标），不触发建单；
 * - 只读已知字段 type/draft/ui，未知字段一律忽略（向前兼容）。
 *   方案词汇对齐：Bot=Router（本接听只做入口路由）；Worker/Trigger 自动跑 = P0 不做。
 */
import { WORKBENCH_HOME_URL } from '../lib/workbench-urls.js'
import { sanitizeOpsBrainDraft } from '../components/ops-bot-mode.js'

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
    // 1.4.10：只读已知字段；draft.text 剥 HTML / 截断 ≤2k，非法即视为无草稿
    const draftText = sanitizeOpsBrainDraft(data.draft)
    const urgency = data.draft?.urgency === 'urgent' ? 'urgent' : 'normal'
    // ui.mode 目前仅 'bot' 一种表现；缺省从 ops-brain 进入也默认 bot（兼容旧无参）
    // 切到运营壳：路由离开 workbench-home → setWorkbenchShellMode(false)
    // 1.4.9：打切入标记，chat-back-hint 据此 toast 一次「点左侧『回工作台』返回」
    try {
      sessionStorage.setItem('ef-from-ops-brain', '1')
    } catch {
      /* 隐私模式等：跳过引导 */
    }
    void import('../components/ops-bot-mode.js').then((m) => {
      // 进 bot-mode（有草稿则挂 pending 预填）；完成后再 navigate，
      // 保证 hashchange 同步时标记已就位
      m.enterOpsBotMode(draftText ? { draftText, urgency } : {})
      return import('../router.js')
    }).then(({ navigate }) => navigate('/chat'))
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
