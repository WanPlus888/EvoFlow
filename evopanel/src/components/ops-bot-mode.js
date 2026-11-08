/**
 * 1.4.10 运营大脑 Bot-mode（P0-1 / P0-5）：#/chat 的 bot 表现态管理
 * 1.4.13（多 Bot 分岗 P0）：默认主表面 = Bot；「更多运营能力」= 全壳出口
 *
 * 方案词汇对齐（运营大脑 Bot 会话模式总规划 §4 P0 / §5 路径A）：
 * - Bot   = Router（入口路由层）：本模块只做「进/出 bot 表现态 + 预填交接」
 * - 后台刀 Worker / 例程工单 Trigger：P0 明确不做（不自动跑模型、不自动建单）
 * - 确认卡 Gate：敏感工具走 tool-approval 面板；文案先落在顶条小字
 *
 * 表现态 = sessionStorage['ef-ops-bot-mode']=1 + #app.evopanel-bot-mode class：
 * - 折叠侧栏会话列表（#shell-chat-panel）等多面板噪音，主列 = 连续对话
 * - 顶条（#ops-bot-strip）：自绘小脑头像 + 专员名「运营大脑」+ 安全小字
 *   + 「更多运营能力」（就地退出 bot-mode，回全壳；驾驶舱/工单/任务路由不删）
 * - 专员条（#ops-specialist-strip，1.4.13）：P0 岗位卡片；点击只预填 `@专员名 `
 * - 侧栏置顶品牌色「回工作台」（1.4.9）不动；顶空条 workbench-mode 规则不回退
 *
 * 生命周期：
 * - 冷启默认（1.4.13）：壳默认路由 = /chat；boot 落在 chat 表面且无
 *   「用户已退出」标记（ef-ops-bot-exited）→ 自动进入 bot-mode（默认 Bot 精简面）
 * - 离开 /chat（点侧栏「驾驶舱」等）= hashchange 自动退出回全壳（并记 exit 标记）
 * - 冷启恢复：仍在 /chat 且标记在 → 重新挂 class；exit 标记在 → 尊重用户选择
 *
 * 预填（P0-3）：draft 经 workbench-home 校验后写
 * evopanel_pending_ops_bot_draft，由 ChatApp 侧 apply-pending-ops-bot-draft 消费，
 * 只写入输入框（pushComposerText → draftVersion → ChatComposer setText）。
 * 硬安全：本模块与其调用链不触发任何发送/扣费/建单链路——
 * 只有用户在输入框点「发送」才出站（草稿永不自动扣费）。
 */

const BOT_MODE_FLAG = 'ef-ops-bot-mode'
const BOT_MODE_EXITED_FLAG = 'ef-ops-bot-exited'
const URGENCY_KEY = 'ef-ops-bot-urgency'
export const OPS_BOT_DRAFT_PENDING_KEY = 'evopanel_pending_ops_bot_draft'

/** chat 表面路由（与 router.isChatRoute 口径一致：/chat 与 /chat-react） */
function isChatSurfacePath(path) {
  const p = String(path || '').split('?')[0]
  return p === '/chat' || p === '/chat-react'
}

/**
 * 契约 §6.2/§6.3：draft.text 只收纯文本——
 * 必须是字符串；剥 HTML 标签与零宽/控制字符；截断 ≤2k；trim 后为空则视为无草稿。
 */
export function sanitizeOpsBrainDraft(raw) {
  if (!raw || typeof raw !== 'object') return ''
  if (typeof raw.text !== 'string') return ''
  return raw.text
    .replace(/<[^>]*>/g, '')
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u200B-\u200D\uFEFF]/g, '')
    .slice(0, 2000)
    .trim()
}

let _stripEl = null
let _urgencyEl = null

/** 进入 bot-mode（幂等）。opts.draftText 为已 sanitize 的纯文本；urgency 仅作标签展示。 */
export function enterOpsBotMode(opts = {}) {
  const draftText = typeof opts?.draftText === 'string' ? opts.draftText : ''
  const urgency = opts?.urgency === 'urgent' ? 'urgent' : 'normal'
  try {
    sessionStorage.setItem(BOT_MODE_FLAG, '1')
    // 进入即清「用户已退出」标记（1.4.13 冷启默认 Bot 的判定依据）
    sessionStorage.removeItem(BOT_MODE_EXITED_FLAG)
    // urgency 只作输入旁标签（顶条「加急」徽标），绝不触发建单
    if (urgency === 'urgent') sessionStorage.setItem(URGENCY_KEY, 'urgent')
    else sessionStorage.removeItem(URGENCY_KEY)
    if (draftText) {
      // ChatApp 侧只把它写进输入框（apply-pending-ops-bot-draft），不含发送链路
      sessionStorage.setItem(
        OPS_BOT_DRAFT_PENDING_KEY,
        JSON.stringify({ text: draftText, urgency }),
      )
    }
  } catch {
    /* 隐私模式等无 sessionStorage：仍尽力给 DOM 表现态 */
  }
  _applyChrome()
}

/** 退出 bot-mode 回全壳（「更多运营能力」/ 离开 chat 表面共用；幂等）。
 *  记 ef-ops-bot-exited 标记：冷启重载时尊重用户已退出的选择（1.4.13）。 */
export function exitOpsBotMode() {
  try {
    sessionStorage.removeItem(BOT_MODE_FLAG)
    sessionStorage.setItem(BOT_MODE_EXITED_FLAG, '1')
    sessionStorage.removeItem(URGENCY_KEY)
  } catch {
    /* ignore */
  }
  _applyChrome()
}

export function isOpsBotMode() {
  try {
    return document.getElementById('app')?.classList.contains('evopanel-bot-mode') || false
  } catch {
    return false
  }
}

function _applyChrome() {
  let active = false
  try {
    // 空.hash 兜底与壳冷启默认路由一致（1.4.13：main.js setDefaultRoute('/chat')）
    active =
      sessionStorage.getItem(BOT_MODE_FLAG) === '1' &&
      isChatSurfacePath(location.hash.slice(1) || '/chat')
  } catch {
    active = false
  }
  document.getElementById('app')?.classList.toggle('evopanel-bot-mode', active)
  if (_urgencyEl) {
    let urgent = false
    try {
      urgent = sessionStorage.getItem(URGENCY_KEY) === 'urgent'
    } catch {
      urgent = false
    }
    _urgencyEl.hidden = !urgent
  }
}

/**
 * 顶条 DOM（一次性挂进 #main-col，位于 #chat-persistent-host 之前）。
 * 自绘 SVG（品牌蓝紫渐变小脑脸），不引第三方 IP、不加重动效依赖。
 */
function _buildStrip() {
  if (_stripEl?.isConnected) return _stripEl
  const mainCol = document.getElementById('main-col')
  const chatHost = document.getElementById('chat-persistent-host')
  if (!mainCol || !chatHost) return null
  const strip = document.createElement('div')
  strip.id = 'ops-bot-strip'
  strip.setAttribute('data-testid', 'ops-bot-strip')
  strip.setAttribute('aria-label', '运营大脑 Bot 模式')
  strip.innerHTML = `
    <span class="ops-bot-avatar" aria-hidden="true">
      <svg viewBox="0 0 28 28" width="24" height="24" focusable="false">
        <defs>
          <linearGradient id="ops-bot-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#5b8def"/>
            <stop offset="1" stop-color="#8b5cf6"/>
          </linearGradient>
        </defs>
        <circle cx="14" cy="14" r="11.5" fill="url(#ops-bot-grad)" stroke="#fff" stroke-width="1.6"/>
        <circle cx="10.2" cy="12.6" r="1.5" fill="#fff"/>
        <circle cx="17.8" cy="12.6" r="1.5" fill="#fff"/>
        <path d="M10.6 16.8c1.1 1.2 2.2 1.8 3.4 1.8s2.3-.6 3.4-1.8" stroke="#fff" stroke-width="1.5" fill="none" stroke-linecap="round"/>
        <circle cx="7.6" cy="15.4" r="1.2" fill="rgba(255,255,255,.35)"/>
        <circle cx="20.4" cy="15.4" r="1.2" fill="rgba(255,255,255,.35)"/>
      </svg>
    </span>
    <div class="ops-bot-id">
      <span class="ops-bot-name">运营大脑</span>
      <span class="ops-bot-sub">先说你想办的事；发送前不会扣费，涉及花钱/真派会再问你</span>
    </div>
    <span class="ops-bot-urgency" data-testid="ops-bot-urgency" hidden>加急</span>
    <button type="button" class="ops-bot-more" data-testid="ops-bot-more-ops"
      title="展开侧栏会话列表与完整运营台（退出 Bot 模式）">更多运营能力</button>
  `
  strip.querySelector('.ops-bot-more')?.addEventListener('click', () => {
    // 一键回全壳：只退出 bot 表现态，不切路由；折叠的会话列表/aside 全貌恢复
    exitOpsBotMode()
  })
  mainCol.insertBefore(strip, chatHost)
  _stripEl = strip
  _urgencyEl = strip.querySelector('[data-testid="ops-bot-urgency"]')
  return strip
}

/**
 * main.js 启动时调用：挂顶条 + 专员条 + hashchange 同步。
 * - 冷启默认 Bot（1.4.13）：落在 chat 表面且无「用户已退出」标记 → 自动进 bot-mode
 * - 离开 chat 表面（侧栏「驾驶舱」等）= 自动退出 bot-mode（全壳可达），并收起转交卡
 * - 冷启仍在 /chat 且标记在 = 恢复 bot 表现态；exit 标记在 = 尊重用户选择不进
 */
export function initOpsBotMode() {
  _buildStrip()
  // 1.4.13 专员条（P0 岗位卡片）：挂在顶条下方，仅 bot-mode 可见（CSS 门）
  try {
    // 动态 import 避免加载顺序耦合；失败不影响 bot 主路径
    void import('./ops-specialist-strip.js')
      .then(({ buildOpsSpecialistStrip }) => buildOpsSpecialistStrip())
      .catch(() => {})
  } catch {
    /* ignore */
  }
  const sync = () => {
    if (!isChatSurfacePath(location.hash.slice(1) || '/chat')) {
      exitOpsBotMode()
      // 离开 chat 表面：收起未决转交卡（会话切换由确认/取消路径自理）
      void import('./ops-handoff-card.js')
        .then(({ dismissOpsHandoffCard }) => dismissOpsHandoffCard())
        .catch(() => {})
    } else {
      _applyChrome()
    }
  }
  window.addEventListener('hashchange', sync)
  // 冷启默认 Bot：chat 表面 + 无已进标记 + 无退出标记 → 进入 bot-mode
  try {
    const entered = sessionStorage.getItem(BOT_MODE_FLAG) === '1'
    const exited = sessionStorage.getItem(BOT_MODE_EXITED_FLAG) === '1'
    if (!entered && !exited && isChatSurfacePath(location.hash.slice(1) || '/chat')) {
      enterOpsBotMode()
    }
  } catch {
    /* 隐私模式等：跳过冷启默认，仅表现态尽力 */
  }
  sync()
}
