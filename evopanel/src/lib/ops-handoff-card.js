/**
 * 运营终端多 Bot 分岗 P0（1.4.13）：转交卡数据形状（形态 C 协议）。
 *
 * Router 或 `@专员` → 生成转交卡（用户可见）；确认后切入专员会话；取消留在 Router。
 * 消息块标记沿用 `__evf_*_v1__:` 前缀惯例（对齐 tool-approval marker）。
 *
 * 硬边界：spend_or_write 恒 false —— 转交本身不花钱、不真派、不建生产单；
 * 确认只是「切到专员会话」，后续任何花钱/真派动作仍走各自确认卡（Gate）。
 */

export const OPS_HANDOFF_MARKER = '__evf_ops_handoff_v1__:'
export const OPS_HANDOFF_TYPE = '__evf_ops_handoff_v1__'

/** 构造转交卡（数据形状 v1）。goal 为用户诉求文本（≤2k，剥两端空白）。 */
export function buildOpsHandoffCard({ to, goal }) {
  return {
    type: OPS_HANDOFF_TYPE,
    to: String(to || '').trim(),
    goal: String(goal || '').trim().slice(0, 2000),
    spend_or_write: false,
    cancelable: true,
  }
}

/** 机器可回放行（system row 文本）：MARKER + JSON。 */
export function opsHandoffCardText(card) {
  return `${OPS_HANDOFF_MARKER}${JSON.stringify(card)}`
}

/** 从 system row 文本解析回卡（非转交卡行返回 null）。 */
export function parseOpsHandoffCard(text) {
  const raw = String(text || '')
  if (!raw.startsWith(OPS_HANDOFF_MARKER)) return null
  try {
    const parsed = JSON.parse(raw.slice(OPS_HANDOFF_MARKER.length))
    if (parsed && typeof parsed === 'object' && parsed.type === OPS_HANDOFF_TYPE) {
      return parsed
    }
  } catch {
    /* ignore */
  }
  return null
}

/** 人可读行（assistant/system 摘要文案）。state: pending | confirmed | cancelled */
export function opsHandoffHumanText(card, state = 'pending') {
  const to = String(card?.to || '')
  const goal = String(card?.goal || '')
  const tail =
    state === 'confirmed'
      ? '（已确认，进入专员会话）'
      : state === 'cancelled'
        ? '（已取消，留在运营大脑）'
        : '（待确认：确认转交 / 取消）'
  return `🤝 转交给专员「${to}」：${goal}${tail}`
}
