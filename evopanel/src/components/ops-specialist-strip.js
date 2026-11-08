/**
 * 多 Bot 分岗 P0（1.4.13）：专员条（bot-mode 顶条下方的 P0 岗位卡片）。
 *
 * - 数据源 = lib/ops-specialists.js（与 backend ops_specialists.py 同码）；
 * - 只在 bot-mode 显示（CSS 门 #app.evopanel-bot-mode；workbench-mode 强制隐藏）；
 * - 点击卡片 = 预填转交：派发 window 事件 `ops-specialist-prefill`
 *   （controller 监听后仅把 `@专员名 ` 写入输入框；无任何自动发送）。
 */

import { getOpsSpecialist, STRIPE_SPECIALIST_CODES } from '../lib/ops-specialists.js'

let _stripEl = null

export const OPS_SPECIALIST_PREFILL_EVENT = 'ops-specialist-prefill'

export function buildOpsSpecialistStrip() {
  if (_stripEl?.isConnected) return _stripEl
  const mainCol = document.getElementById('main-col')
  const chatHost = document.getElementById('chat-persistent-host')
  if (!mainCol || !chatHost) return null
  const strip = document.createElement('div')
  strip.id = 'ops-specialist-strip'
  strip.setAttribute('data-testid', 'ops-specialist-strip')
  strip.setAttribute('aria-label', 'P0 专员')
  const cards = STRIPE_SPECIALIST_CODES.map((code) => {
    const sp = getOpsSpecialist(code)
    if (!sp) return ''
    return `
      <button type="button" class="ops-specialist-card" data-code="${sp.code}"
        data-testid="ops-specialist-card-${sp.code}" title="转交给「${sp.name}」（只预填，不发送）">
        <span class="ops-specialist-name">${sp.name}</span>
        <span class="ops-specialist-short">${sp.short}</span>
      </button>
    `
  }).join('')
  strip.innerHTML = cards
  strip.querySelectorAll('.ops-specialist-card').forEach((btn) => {
    btn.addEventListener('click', () => {
      const code = btn.getAttribute('data-code') || ''
      const sp = getOpsSpecialist(code)
      if (!sp) return
      // 只预填：controller 监听本事件，把 `@名 ` 写进输入框；绝不自动发送
      window.dispatchEvent(
        new CustomEvent(OPS_SPECIALIST_PREFILL_EVENT, {
          detail: { code: sp.code, name: sp.name },
        }),
      )
    })
  })
  mainCol.insertBefore(strip, chatHost)
  _stripEl = strip
  return strip
}
