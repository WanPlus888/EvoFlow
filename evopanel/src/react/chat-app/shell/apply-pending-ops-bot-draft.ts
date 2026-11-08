/**
 * 1.4.10 运营大脑 Bot 预填（P0-3）：消费 evopanel_pending_ops_bot_draft。
 *
 * 只把文本写进 Composer（pushComposerText → composerDraftVersion →
 * ChatComposer setText），文本进输入框、用户可改；消费即删 key（幂等）。
 *
 * 硬安全（总规划 §7.3）：本文件与调用链不触碰任何发送/计费/建单接口——
 * 只有用户在输入框点「发送」才出站；草稿永不自动扣费。
 */
export const OPS_BOT_DRAFT_PENDING_KEY = 'evopanel_pending_ops_bot_draft'

export type PushComposerText = (next: string) => void

/** 返回实际预填的文本（空 = 无 pending）；绝不触发发送。 */
export function applyPendingOpsBotDraft(pushComposerText: PushComposerText): string {
  let raw: string | null = null
  try {
    raw = sessionStorage.getItem(OPS_BOT_DRAFT_PENDING_KEY)
    if (!raw) return ''
    sessionStorage.removeItem(OPS_BOT_DRAFT_PENDING_KEY)
  } catch {
    return ''
  }
  let text = ''
  try {
    const parsed = JSON.parse(raw) as { text?: unknown }
    if (typeof parsed?.text === 'string') text = parsed.text
  } catch {
    text = ''
  }
  if (!text) return ''
  // 仅写输入框（语音桥同款通道）；此处没有任何出站调用
  pushComposerText(text)
  return text
}
