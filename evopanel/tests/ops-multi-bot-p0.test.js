/**
 * 多 Bot 分岗 P0（1.4.13）回归：
 * - 默认 Bot 精简面（冷启 /chat + bot-mode；更多运营能力 = 全壳出口）
 * - 形态 C：专员条 + 转交卡（__evf_ops_handoff_v1__）+ @专员不走巡检派发
 * - 投放建议草稿 Gate（ad_suggestion_submit_for_review = confirm）
 * - 预填链路硬安全（无发送/调模型/扣费/建单）
 * 源码断言风格与 ops-bot-mode.test.js 一致；纯函数模块做行为单测。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = process.cwd()
const MAIN_JS = readFileSync(join(ROOT, 'src/main.js'), 'utf8')
const OPS_BOT_MODE = readFileSync(join(ROOT, 'src/components/ops-bot-mode.js'), 'utf8')
const WORKBENCH_HOME = readFileSync(join(ROOT, 'src/pages/workbench-home.js'), 'utf8')
const OPS_SPECIALISTS_SRC = readFileSync(join(ROOT, 'src/lib/ops-specialists.js'), 'utf8')
const OPS_HANDOFF_CARD_LIB = readFileSync(join(ROOT, 'src/lib/ops-handoff-card.js'), 'utf8')
const OPS_SPECIALIST_STRIP = readFileSync(
  join(ROOT, 'src/components/ops-specialist-strip.js'),
  'utf8',
)
const OPS_HANDOFF_CARD_DOM = readFileSync(
  join(ROOT, 'src/components/ops-handoff-card.js'),
  'utf8',
)
const CHAT_COMPOSER = readFileSync(join(ROOT, 'src/react/components/ChatComposer.tsx'), 'utf8')
const CONTROLLER = readFileSync(
  join(ROOT, 'src/react/chat-app/use-chat-app-controller.tsx'),
  'utf8',
)
const DISPATCH_EMPLOYEE = readFileSync(
  join(ROOT, 'src/react/chat-app/dispatch/handle-dispatch-employee.ts'),
  'utf8',
)
const TOOL_APPROVAL = readFileSync(join(ROOT, 'src/lib/tool-approval.js'), 'utf8')
const LAYOUT_CSS = readFileSync(join(ROOT, 'src/style/layout.css'), 'utf8')
const BACKEND_SPECIALISTS = readFileSync(
  join(ROOT, '../backend/packages/harness/evoflow/collab/ops_specialists.py'),
  'utf8',
)
const VERSION = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim()

// 纯函数模块（无 DOM 依赖，可直接 import）
import {
  matchOpsSpecialistMention,
  isOpsSpecialistCode,
  OPS_SPECIALISTS,
  STRIPE_SPECIALIST_CODES,
} from '../src/lib/ops-specialists.js'
import {
  buildOpsHandoffCard,
  opsHandoffCardText,
  parseOpsHandoffCard,
  opsHandoffHumanText,
} from '../src/lib/ops-handoff-card.js'

describe('1.4.13 默认 Bot 精简面（Jennifer 2026-11-09 覆盖）', () => {
  it('壳默认路由 = /chat（不再是 workbench-home）；/workbench-home 路由注册保留', () => {
    expect(MAIN_JS).toContain("setDefaultRoute('/chat')")
    expect(MAIN_JS).not.toContain("setDefaultRoute('/workbench-home')")
    expect(MAIN_JS).toMatch(/registerRoute\('\/workbench-home'/)
  })

  it('冷启默认进 bot-mode：无 exit 标记 + chat 表面 → enterOpsBotMode', () => {
    expect(OPS_BOT_MODE).toContain("'ef-ops-bot-exited'")
    expect(OPS_BOT_MODE).toMatch(/if \(!entered && !exited && isChatSurfacePath/)
    expect(OPS_BOT_MODE).toMatch(/enterOpsBotMode\(\)/)
    // 进 bot 清 exit 标记；退出写 exit 标记（重载尊重用户选择）
    expect(OPS_BOT_MODE).toMatch(/sessionStorage\.removeItem\(BOT_MODE_EXITED_FLAG\)/)
    expect(OPS_BOT_MODE).toMatch(/sessionStorage\.setItem\(BOT_MODE_EXITED_FLAG, '1'\)/)
  })

  it('「更多运营能力」仍就地退出（exitOpsBotMode）；离开 chat hashchange 退出保留', () => {
    expect(OPS_BOT_MODE).toContain('更多运营能力')
    expect(OPS_BOT_MODE).toMatch(/ops-bot-more.*exitOpsBotMode/s)
    expect(OPS_BOT_MODE).toContain("window.addEventListener('hashchange', sync)")
  })

  it('无参 / draft / ui.mode:bot 的 ops-brain 一律 enterOpsBotMode + /chat（1.4.10 路径钉死）', () => {
    expect(WORKBENCH_HOME).toMatch(/enterOpsBotMode\(draftText \? \{ draftText, urgency \} : \{\}\)/)
    expect(WORKBENCH_HOME).toContain("navigate('/chat')")
  })
})

describe('1.4.13 形态 C：专员注册表 + 专员条 + 转交卡', () => {
  it('P0 五岗双侧同码（壳 lib 与 backend ops_specialists.py）', () => {
    const codes = OPS_SPECIALISTS.map((s) => s.code)
    expect(codes).toEqual([
      'ops-brain-router',
      'main-image-op',
      'ticket-accept-op',
      'knowledge-deposit-op',
      'ad-watch-op',
    ])
    for (const code of codes) {
      expect(BACKEND_SPECIALISTS).toContain(`"${code}"`)
    }
    // 专员条不含 Router（Router = 顶条本身）
    expect(STRIPE_SPECIALIST_CODES).not.toContain('ops-brain-router')
  })

  it('matchOpsSpecialistMention：中文名 / code / 带不带空格均可；不命中返回 null', () => {
    expect(matchOpsSpecialistMention('@主图·套图专员 给 A01 换主图')).toEqual({
      code: 'main-image-op',
      name: '主图·套图专员',
      goal: '给 A01 换主图',
    })
    expect(matchOpsSpecialistMention('@ad-watch-op 出今日盯盘日报')).toEqual({
      code: 'ad-watch-op',
      name: '投放盯盘专员',
      goal: '出今日盯盘日报',
    })
    expect(matchOpsSpecialistMention('@运营大脑')).toBeNull() // 无 goal → 不劫持
    expect(matchOpsSpecialistMention('普通消息 @主图·套图专员')).toBeNull() // 非开头
    expect(matchOpsSpecialistMention('你好')).toBeNull()
    expect(isOpsSpecialistCode('main-image-op')).toBe(true)
    expect(isOpsSpecialistCode('tuantu-op')).toBe(false) // 旧生产岗仍走 @员工 派发
  })

  it('转交卡协议：marker v1 + 构造/回放往返 + 取消文案存在', () => {
    const card = buildOpsHandoffCard({ to: 'ad-watch-op', goal: '预算建议' })
    expect(card.type).toBe('__evf_ops_handoff_v1__')
    expect(card.spend_or_write).toBe(false)
    expect(card.cancelable).toBe(true)
    const parsed = parseOpsHandoffCard(opsHandoffCardText(card))
    expect(parsed).toEqual(card)
    expect(parseOpsHandoffCard('普通行')).toBeNull()
    expect(opsHandoffHumanText(card, 'cancelled')).toContain('已取消')
    expect(opsHandoffHumanText(card, 'confirmed')).toContain('已确认')
  })

  it('专员条 DOM：卡片 + 点击只派 ops-specialist-prefill 事件（预填，不发送）', () => {
    expect(OPS_SPECIALIST_STRIP).toContain("id = 'ops-specialist-strip'")
    expect(OPS_SPECIALIST_STRIP).toContain('ops-specialist-card')
    expect(OPS_SPECIALIST_STRIP).toContain('ops-specialist-prefill')
    expect(OPS_SPECIALIST_STRIP).not.toMatch(/handleSend|invokeModel|charge|createTicket/)
  })

  it('转交卡 DOM：确认/取消两键 + dismiss 幂等', () => {
    expect(OPS_HANDOFF_CARD_DOM).toContain("id = 'ops-handoff-card'")
    expect(OPS_HANDOFF_CARD_DOM).toContain('ops-handoff-confirm')
    expect(OPS_HANDOFF_CARD_DOM).toContain('ops-handoff-cancel')
    expect(OPS_HANDOFF_CARD_DOM).toContain('dismissOpsHandoffCard')
    expect(OPS_HANDOFF_CARD_DOM).toContain('onCancel')
  })

  it('CSS：专员条/转交卡只在 bot-mode 露出；workbench-mode 强制隐藏', () => {
    expect(LAYOUT_CSS).toMatch(/#app\.evopanel-bot-mode #ops-specialist-strip\s*\{[\s\S]*?display: flex/)
    expect(LAYOUT_CSS).toMatch(
      /#app\.evopanel-workbench-mode #ops-specialist-strip\s*\{[\s\S]*?display: none !important/,
    )
    expect(LAYOUT_CSS).toMatch(/#app\.evopanel-bot-mode #ops-handoff-card\s*\{[\s\S]*?display: flex/)
    expect(LAYOUT_CSS).toMatch(
      /#app\.evopanel-workbench-mode #ops-handoff-card\s*\{[\s\S]*?display: none !important/,
    )
  })
})

describe('1.4.13 @专员 不走 proactiveDispatchTask 巡检派发', () => {
  it('ChatComposer：P0 专员优先走 onOpsSpecialistHandoff 分支（先于 onDispatchEmployee）', () => {
    expect(CHAT_COMPOSER).toContain('onOpsSpecialistHandoff')
    expect(CHAT_COMPOSER).toContain('isOpsSpecialistCode(dispatch.agent_code)')
    expect(CHAT_COMPOSER).toContain('matchOpsSpecialistMention(t)')
    // 专员分支在员工派发分支之前
    const specialistIdx = CHAT_COMPOSER.indexOf('onOpsSpecialistHandoff(specialist.code')
    const dispatchIdx = CHAT_COMPOSER.indexOf('onDispatchEmployee(dispatch.agent_code')
    expect(specialistIdx).toBeGreaterThan(-1)
    expect(dispatchIdx).toBeGreaterThan(specialistIdx)
  })

  it('controller 转交链路无 proactiveDispatchTask；旧 @员工派发仍保留在 dispatch 模块', () => {
    expect(CONTROLLER).toContain('handleOpsSpecialistHandoff')
    expect(CONTROLLER).toContain('__evf_ops_handoff_v1__') // 经 lib 常量引用（opsHandoffCardText）
    expect(CONTROLLER).not.toMatch(/proactiveDispatchTask/)
    // 旧路径（非专员 proactive 员工）不动：
    expect(DISPATCH_EMPLOYEE).toContain('proactiveDispatchTask')
    expect(DISPATCH_EMPLOYEE).not.toContain('ops-specialist')
  })

  it('controller：转交确认只建会话 + 预填 goal（pushComposerText），不自动发送', () => {
    expect(CONTROLLER).toMatch(/agentCode: code/)
    expect(CONTROLLER).toMatch(/pushComposerText\(goal\)/)
    const ctx = CONTROLLER.slice(
      CONTROLLER.indexOf('handleOpsSpecialistHandoff = useCallback'),
      CONTROLLER.indexOf('handleOpsSpecialistHandoff = useCallback') + 4500,
    )
    expect(ctx).not.toMatch(/handleSend|invokeModel|charge\b|createTicket/)
  })
})

describe('1.4.13 投放建议草稿 Gate + 壳风险表同步', () => {
  it('tool-approval.js：submit_for_review=confirm；草稿族=auto', () => {
    expect(TOOL_APPROVAL).toMatch(/ad_suggestion_submit_for_review:\s*RISK_CONFIRM/)
    for (const t of [
      'ad_watch_daily_draft',
      'ad_anomaly_card_draft',
      'ad_suggestion_draft_create',
      'ad_suggestion_draft_update',
      'ad_suggestion_draft_list',
      'ad_suggestion_draft_get',
      'ticket_accept_note_draft',
      'ticket_todo_draft',
      'team_knowledge_propose_draft',
    ]) {
      expect(TOOL_APPROVAL).toMatch(new RegExp(`${t}:\\s*RISK_AUTO`))
    }
  })
})

describe('1.4.13 预填链路硬安全（专员条/handoff 卡同规约）', () => {
  it('新模块源码不含发送/调模型/扣费/建单链路', () => {
    const sources = [OPS_SPECIALIST_STRIP, OPS_HANDOFF_CARD_DOM, OPS_HANDOFF_CARD_LIB, OPS_SPECIALISTS_SRC]
    for (const src of sources) {
      expect(src).not.toMatch(/handleSend|invokeModel|charge\b|createTicket|chatSend/)
    }
  })
})

describe('1.4.13 版本', () => {
  it('VERSION === 1.4.13', () => {
    expect(VERSION).toBe('1.4.13')
  })
})
