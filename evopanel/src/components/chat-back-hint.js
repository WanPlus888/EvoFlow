/**
 * 1.4.9 回工作台去重：#/chat 一次侧栏引导 toast
 *
 * 1.4.8 的 #/chat 顶栏薄条（chat-return-bar 显性回程按钮）已删——与
 * 侧栏「回工作台」重复。回程入口收敛为侧栏置顶品牌色按钮（shell-aside）。
 *
 * 本组件只保留一次性引导：工作台 ops-brain postMessage 切入 /chat 后，
 * toast 提示「点左侧『回工作台』返回」（文案指向侧栏，不再提「上方」）。
 * 双 sessionStorage 键防刷屏：ef-from-ops-brain（切入标记，读后即清）+
 * ef-chat-back-hint-shown（本会话只提醒一次）。
 */
import { getCurrentRoute } from '../router.js'

const OPS_BRAIN_FLAG = 'ef-from-ops-brain'
const HINT_SHOWN = 'ef-chat-back-hint-shown'
let _initialized = false

function isChatRoute(path) {
  const p = String(path || '').split('?')[0]
  return p === '/chat' || p === '/chat-react'
}

function maybeToastOnce() {
  try {
    if (sessionStorage.getItem(OPS_BRAIN_FLAG) !== '1') return
    sessionStorage.removeItem(OPS_BRAIN_FLAG)
    if (sessionStorage.getItem(HINT_SHOWN) === '1') return
    sessionStorage.setItem(HINT_SHOWN, '1')
    void import('./toast.js').then(({ toast }) => {
      toast('已切到运营大脑：点左侧『回工作台』可返回工作台首页', 'info', { duration: 5000 })
    })
  } catch {
    /* sessionStorage 不可用（隐私模式等）时静默跳过引导 */
  }
}

export function initChatBackHint() {
  if (_initialized) return
  _initialized = true
  const sync = () => {
    if (isChatRoute(getCurrentRoute())) maybeToastOnce()
  }
  window.addEventListener('hashchange', sync)
  // 冷启直达 /chat（无 hashchange）也补检一次
  sync()
}
