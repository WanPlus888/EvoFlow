/**
 * 1.4.8 回工作台：#/chat（运营大脑）顶上常驻薄条
 *
 * 背景：从工作台 ops-brain postMessage 切到 /chat 后，运营壳侧栏虽有
 * 「回工作台」入口（1.4.8 上移），但用户进对话后注意力不在侧栏 —— Jennifer
 * 反馈「找不到回工作台」。本组件在 ChatApp 可见时于其上方显示一条薄栏，
 * 内含显性「← 回工作台」按钮，click → navigate('/workbench-home')。
 *
 * 显隐纯 CSS 门控（#main-col:has(> #chat-persistent-host:not([hidden]))），
 * 与 router.setChatHostVisible 的 hidden/display 切换天然同步；本模块只负责
 * 绑定回程点击 + 一次引导 toast（ops-brain 切入时提示，sessionStorage 防刷屏）。
 */
import { getCurrentRoute, navigate } from '../router.js'

const OPS_BRAIN_FLAG = 'ef-from-ops-brain'
const OPS_BRAIN_TOAST_SHOWN = 'ef-opsbrain-toast-shown'
let _initialized = false

function isChatRoute(path) {
  const p = String(path || '').split('?')[0]
  return p === '/chat' || p === '/chat-react'
}

/**
 * 工作台 ops-brain → /chat 切入后，toast 一次「可点『回工作台』返回」。
 * 双键防刷屏：ef-from-ops-brain（切入标记，读后即清）+ ef-opsbrain-toast-shown（本会话只提醒一次）。
 */
function maybeToastOnce() {
  try {
    if (sessionStorage.getItem(OPS_BRAIN_FLAG) !== '1') return
    sessionStorage.removeItem(OPS_BRAIN_FLAG)
    if (sessionStorage.getItem(OPS_BRAIN_TOAST_SHOWN) === '1') return
    sessionStorage.setItem(OPS_BRAIN_TOAST_SHOWN, '1')
    void import('./toast.js').then(({ toast }) => {
      toast('已切到运营大脑：点上方「回工作台」可返回工作台首页', 'info', { duration: 5000 })
    })
  } catch {
    /* sessionStorage 不可用（隐私模式等）时静默跳过引导 */
  }
}

export function initChatReturnBar() {
  if (_initialized) return
  const bar = document.getElementById('shell-chat-return-bar')
  const btn = document.getElementById('shell-chat-return-btn')
  if (!bar || !btn) return
  _initialized = true

  btn.addEventListener('click', () => {
    navigate('/workbench-home')
  })

  const sync = () => {
    if (isChatRoute(getCurrentRoute())) maybeToastOnce()
  }
  window.addEventListener('hashchange', sync)
  // 冷启直达 /chat（无 hashchange）也补检一次
  sync()
}
