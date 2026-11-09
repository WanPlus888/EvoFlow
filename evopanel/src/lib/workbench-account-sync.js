/**
 * 工作台账号同步器（1.4.18 运营终端账号默认 = 工作台账号）。
 *
 * 与 src-tauri/src/workbench_sso_shim.js 配对：垫片活在工作台 iframe 里
 * （把 wb_token 变化 postMessage 给壳），本模块活在壳主窗，收消息后调网关
 * `POST /api/webui/login-workbench-token` 验真换壳 JWT → 账号跟随工作台。
 *
 * 安全边界：
 * - 只收 origin === https://workbench.kll666.cn 且 source 是页面内某 iframe
 *   的 contentWindow 的消息（AC8）；只读 type/token/reason/nonce 字段。
 * - 工作台 token 只存 sessionStorage（本会话），不落 localStorage；错误路径
 *   静默，绝不回退 Local Admin、绝不弹登录页。
 * - 「本机运维登录」（#/login?switch=1&local=1）置 ef-local-ops-pin，本会话
 *   内不被自动覆盖（AC5）；退出账号即恢复自动同步。
 * - 工作台退出（token=null）不动壳（P0 不因工作台退出而清壳）。
 */
import { ensureMeReady, prepareAccountSwitch, refreshMe } from './account-session.js'
import { loginWithWorkbenchToken, saveAuthToken } from './webui-remote.js'
import { toast } from '../components/toast.js'

const WB_ORIGIN = 'https://workbench.kll666.cn'
const SSO_TOKEN_KEY = 'evoflow_wb_sso_token'
const LOCAL_OPS_PIN = 'ef-local-ops-pin'
const GW_NOT_UPGRADED_KEY = 'ef-wb-sync-gw-not-upgraded'
const RELOAD_FLAG_KEY = 'ef-wb-sync-reload'
const DEBOUNCE_MS = 500

/** @type {boolean} */
let _inited = false
/** @type {string | null} 最近一次成功处理的工作台 token 的 SHA-256（去重） */
let _lastTokenHash = null
/** @type {boolean} 串行锁：同一时刻只跑一次换号流程 */
let _busy = false
/** @type {string | null} 防抖窗口内最新待处理 token */
let _pendingToken = null
/** @type {ReturnType<typeof setTimeout> | null} */
let _debounceTimer = null
/** @type {(ev: MessageEvent) => void} */
let _onMessage = null

/** @param {string} text @returns {Promise<string>} */
async function sha256Hex(text) {
  try {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('')
  } catch {
    // crypto.subtle 不可用（极老 WebView）：退化为内存中的原始值引用比对（不落盘）。
    return `plain:${text}`
  }
}

/** AC8：source 必须是页面内某个 iframe 的 contentWindow。 */
function sourceIsKnownIframe(ev) {
  try {
    const frames = document.querySelectorAll('iframe')
    for (const f of frames) {
      if (f.contentWindow === ev.source) return true
    }
  } catch {
    /* ignore */
  }
  return false
}

/** @returns {string} 当前路由 path（'#/chat?x' → '/chat'） */
function currentRoute() {
  try {
    return (window.location.hash.slice(1) || '/chat').split('?')[0]
  } catch {
    return '/chat'
  }
}

/**
 * @param {string} message
 * @param {'info'|'success'|'warning'} [type]
 */
function showToast(message, type = 'info') {
  try {
    toast(message, type, { key: 'wb-account-sync', force: true })
  } catch {
    /* toast 挂了不影响同步主流程 */
  }
}

/**
 * 处理一条已验源的工作台 token：验真 → 同账号 no-op / 换号。
 * @param {string} token
 */
async function syncToken(token) {
  const hash = await sha256Hex(token)
  if (hash === _lastTokenHash) return // 同 token 已处理过（AC4 去重）

  /** @type {{ token: string, username: string }} */
  let resp
  try {
    resp = await loginWithWorkbenchToken({ workbench_token: token })
  } catch (err) {
    const status = Number(err?.status) || 0
    if (status === 404 || status === 405) {
      // 网关未升级（连的还是旧远程网关）：提示一次，不循环（AC6）。
      console.warn('[wb-account-sync] gateway missing /webui/login-workbench-token', status)
      try {
        if (sessionStorage.getItem(GW_NOT_UPGRADED_KEY) !== '1') {
          sessionStorage.setItem(GW_NOT_UPGRADED_KEY, '1')
          showToast('网关未升级，账号暂不能自动同步', 'warning')
        }
      } catch {
        /* ignore */
      }
      return
    }
    // 401（工作台 token 失效）/ 5xx / 超时：静默，下次事件再试；不记去重。
    return
  }
  if (!resp || !resp.token || !resp.username) return

  // 已是该账号（JWT 会话）→ 什么都不动（不清缓存、不刷新，AC4）。
  let me = null
  try {
    me = await ensureMeReady()
  } catch {
    /* me 拉不到 → 继续走换号（网关刚验真过 token，可以切） */
  }
  if (me && me.authSource === 'jwt' && me.username === resp.username) {
    _lastTokenHash = hash
    try {
      sessionStorage.setItem(SSO_TOKEN_KEY, token)
    } catch {
      /* ignore */
    }
    return
  }

  // 换号：清缓存 → 存壳 JWT → 记工作台 token（供 sso-request 应答）→ 刷 me。
  prepareAccountSwitch(resp.token)
  saveAuthToken(resp.token)
  try {
    sessionStorage.setItem(SSO_TOKEN_KEY, token)
    sessionStorage.removeItem(GW_NOT_UPGRADED_KEY)
  } catch {
    /* ignore */
  }
  _lastTokenHash = hash
  await refreshMe({ retries: 2 })
  showToast(`已同步为工作台账号 @${resp.username}`, 'success')

  // 刷新整壳让所有模块吃到新身份；/workbench-home 下不 reload（iframe 会
  // 整页重载 → 垫片再报 identity → 死循环），靠 account-changed 事件自愈。
  if (currentRoute() === '/workbench-home') return
  try {
    if (sessionStorage.getItem(RELOAD_FLAG_KEY) === resp.username) return // 同号只 reload 一次
    sessionStorage.setItem(RELOAD_FLAG_KEY, resp.username)
  } catch {
    /* ignore */
  }
  window.location.reload()
}

function processPending() {
  if (_busy || !_pendingToken) return
  const token = _pendingToken
  _pendingToken = null
  _busy = true
  Promise.resolve()
    .then(() => syncToken(token))
    .catch((e) => console.warn('[wb-account-sync] sync failed', e))
    .finally(() => {
      _busy = false
      if (_pendingToken) {
        queueToken(_pendingToken)
        _pendingToken = null
      }
    })
}

/** 500ms 防抖 + 串行（processPending 持锁）。 */
function queueToken(token) {
  _pendingToken = token
  if (_debounceTimer) clearTimeout(_debounceTimer)
  _debounceTimer = setTimeout(() => {
    _debounceTimer = null
    processPending()
  }, DEBOUNCE_MS)
}

/**
 * @param {MessageEvent} ev
 */
function onMessage(ev) {
  if (ev.origin !== WB_ORIGIN) return
  if (!sourceIsKnownIframe(ev)) return
  const data = ev.data
  if (!data || typeof data !== 'object') return
  const type = data.type

  // 壳 → 工作台：iframe 没登录，垫片来要 token（AC3）。
  if (type === 'evoflow-wb-sso-request') {
    let token = null
    try {
      token = sessionStorage.getItem(SSO_TOKEN_KEY)
    } catch {
      token = null
    }
    try {
      ev.source.postMessage(
        { type: 'evoflow-wb-sso-reply', nonce: data.nonce, token },
        WB_ORIGIN,
      )
    } catch {
      /* ignore */
    }
    return
  }

  // 工作台 → 壳：token 出现/变化。
  if (type !== 'evoflow-wb-identity') return
  const token = typeof data.token === 'string' && data.token ? data.token : null
  if (!token) return // P0：工作台退出不清壳
  let pinned = false
  try {
    pinned = sessionStorage.getItem(LOCAL_OPS_PIN) === '1'
  } catch {
    pinned = false
  }
  if (pinned) return // 本机运维旁路：本会话不被自动覆盖（AC5）
  queueToken(token)
}

/** 幂等初始化（main.js boot 里调用；Tauri 与浏览器都挂）。 */
export function initWorkbenchAccountSync() {
  if (_inited) return
  _inited = true
  _onMessage = onMessage
  window.addEventListener('message', _onMessage)
}

/** 测试专用：还原全部模块级状态并注销监听。 */
export function __resetForTest() {
  if (_onMessage) {
    try {
      window.removeEventListener('message', _onMessage)
    } catch {
      /* ignore */
    }
  }
  if (_debounceTimer) clearTimeout(_debounceTimer)
  _inited = false
  _lastTokenHash = null
  _busy = false
  _pendingToken = null
  _debounceTimer = null
  _onMessage = null
}
