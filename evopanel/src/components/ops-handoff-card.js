/**
 * 多 Bot 分岗 P0（1.4.13）：转交卡（vanilla DOM，形态 C）。
 *
 * Router / `@专员` 触发后，在 #main-col 露出一张卡：
 * - 「确认转交」→ onConfirm（controller 切入专员会话；转交本身零扣费零真派）
 * - 「取消」→ onCancel（留在运营大脑 Router）
 * 只在 bot-mode 显示（CSS 门同 #ops-bot-strip）；单实例幂等（新卡覆盖旧卡）。
 */

let _cardEl = null

/**
 * 露出转交卡。opts：
 * - to / toName：专员 code 与显示名（必填）
 * - goal：转交目标文本
 * - onConfirm / onCancel：动作回调（由调用方负责会话切换与回执行）
 */
export function showOpsHandoffCard({ to, toName, goal, onConfirm, onCancel }) {
  dismissOpsHandoffCard()
  const mainCol = document.getElementById('main-col')
  const chatHost = document.getElementById('chat-persistent-host')
  if (!mainCol || !chatHost) return null
  const card = document.createElement('div')
  card.id = 'ops-handoff-card'
  card.setAttribute('data-testid', 'ops-handoff-card')
  card.setAttribute('data-to', String(to || ''))
  card.setAttribute('aria-label', '专员转交卡')
  card.innerHTML = `
    <div class="ops-handoff-main">
      <span class="ops-handoff-badge">转交</span>
      <span class="ops-handoff-to" data-testid="ops-handoff-to">${toName || to}</span>
      <span class="ops-handoff-goal" data-testid="ops-handoff-goal"></span>
    </div>
    <div class="ops-handoff-note">转交不花钱、不真派；确认后进入专员会话，花钱/真派仍会弹确认卡</div>
    <div class="ops-handoff-actions">
      <button type="button" class="ops-handoff-confirm" data-testid="ops-handoff-confirm">确认转交</button>
      <button type="button" class="ops-handoff-cancel" data-testid="ops-handoff-cancel">取消</button>
    </div>
  `
  card.querySelector('.ops-handoff-goal').textContent = String(goal || '')
  card.querySelector('.ops-handoff-confirm').addEventListener('click', () => {
    dismissOpsHandoffCard()
    try {
      onConfirm?.()
    } catch (e) {
      console.warn('[ops-handoff-card] confirm failed', e)
    }
  })
  card.querySelector('.ops-handoff-cancel').addEventListener('click', () => {
    dismissOpsHandoffCard()
    try {
      onCancel?.()
    } catch (e) {
      console.warn('[ops-handoff-card] cancel failed', e)
    }
  })
  mainCol.insertBefore(card, chatHost)
  _cardEl = card
  return card
}

/** 收起转交卡（幂等；离开 chat 表面 / 完成动作时调用）。 */
export function dismissOpsHandoffCard() {
  if (_cardEl?.isConnected) _cardEl.remove()
  _cardEl = null
}
