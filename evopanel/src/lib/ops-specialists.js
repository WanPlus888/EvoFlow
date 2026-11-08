/**
 * 运营终端多 Bot 分岗 P0（1.4.13）：壳侧专员注册表镜像。
 *
 * 与 backend `evoflow/collab/ops_specialists.py` 的 `_SPECIALISTS` 保持同码
 * （测例 ops-multi-bot-p0.test.js 断言两侧 code 集一致）。
 * 可扩展挂载点：新增专员 = 两侧注册表各加一条种子，不改 Router 主路径。
 *
 * 岗位边界（§0 钉死口径）：
 * - 运营大脑 Router：默认主对话；转交只产 handoff 意图，不真派；
 * - 主图·套图：白名单工具；submit 仍确认卡；
 * - 工单验收 / 知识沉淀：只有本地草稿（无生产写 / 无自动 accept）；
 * - 投放盯盘：「可写」⊆ ad_* 草稿白名单 1–6；零投放平台生产写。
 */

export const OPS_SPECIALISTS = [
  {
    code: 'ops-brain-router',
    name: '运营大脑',
    short: '听需求、拆任务、按岗转交',
    router: true,
  },
  {
    code: 'main-image-op',
    name: '主图·套图专员',
    short: '商品主图/套图生成与跟踪',
  },
  {
    code: 'ticket-accept-op',
    name: '工单验收专员',
    short: '验收笔记与待办草稿',
  },
  {
    code: 'knowledge-deposit-op',
    name: '知识沉淀专员',
    short: '团队知识建议草稿',
  },
  {
    code: 'ad-watch-op',
    name: '投放盯盘专员',
    short: '盯盘日报/异常卡/建议单草稿',
  },
]

/** Router 之外、可上「专员条」的岗位（与 backend STRIPE_SPECIALIST_CODES 一致） */
export const STRIPE_SPECIALIST_CODES = [
  'main-image-op',
  'ticket-accept-op',
  'knowledge-deposit-op',
  'ad-watch-op',
]

export function getOpsSpecialist(code) {
  const c = String(code || '').trim()
  return OPS_SPECIALISTS.find((s) => s.code === c) || null
}

export function isOpsSpecialistCode(code) {
  return getOpsSpecialist(code) !== null
}

/**
 * 解析消息开头的 `@专员` 提及（P0 codes / 中文名均可）：
 * 返回 { code, name, goal } 或 null（不命中则回落普通聊天 / 旧 @员工派发）。
 * 与 ChatComposer.parseEmployeeMention 同风格：长名优先，空格可选。
 */
export function matchOpsSpecialistMention(text) {
  const raw = String(text || '').trimStart()
  if (!raw.startsWith('@')) return null
  const sorted = [...OPS_SPECIALISTS].sort((a, b) => b.name.length - a.name.length)
  for (const s of sorted) {
    const name = String(s.name || '').trim()
    if (!name) continue
    if (raw.length > name.length + 1 && raw.slice(1, 1 + name.length) === name) {
      const goal = raw.slice(1 + name.length).replace(/^[\s:：]+/, '').trim()
      if (goal) return { code: s.code, name, goal }
    }
    // @code 形式（英文 code，须后随空格避免误吞邮箱类文本）
    if (
      raw.length > s.code.length + 2 &&
      raw.slice(1, 1 + s.code.length) === s.code &&
      /^[\s:：]/.test(raw.slice(1 + s.code.length, 2 + s.code.length))
    ) {
      const goal = raw.slice(1 + s.code.length).replace(/^[\s:：]+/, '').trim()
      if (goal) return { code: s.code, name, goal }
    }
  }
  return null
}
