import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// vitest 的 root 即 evopanel/（见 workbench-mode-shell.test.js 同款注释）
const ROOT = process.cwd()
const WORKBENCH_HOME = readFileSync(join(ROOT, 'src/pages/workbench-home.js'), 'utf8')
const OPS_BOT_MODE = readFileSync(join(ROOT, 'src/components/ops-bot-mode.js'), 'utf8')
const APPLY_DRAFT = readFileSync(
  join(ROOT, 'src/react/chat-app/shell/apply-pending-ops-bot-draft.ts'),
  'utf8',
)
const SHELL_LISTENERS = readFileSync(
  join(ROOT, 'src/react/chat-app/shell/install-shell-window-listeners.ts'),
  'utf8',
)
const CONTROLLER = readFileSync(
  join(ROOT, 'src/react/chat-app/use-chat-app-controller.tsx'),
  'utf8',
)
const LAYOUT_CSS = readFileSync(join(ROOT, 'src/style/layout.css'), 'utf8')
const MAIN_JS = readFileSync(join(ROOT, 'src/main.js'), 'utf8')
const SHELL_ASIDE = readFileSync(join(ROOT, 'src/components/shell-aside.js'), 'utf8')
const VERSION = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim()

describe('1.4.10 契约扩展：evoflow-ops-brain + draft/ui（无参兼容）', () => {
  it('无参路径 ≡ 1.4.9：双 type 仍认 + navigate(/chat) + ef-from-ops-brain 标记 + 源校验', () => {
    expect(WORKBENCH_HOME).toContain("'evoflow-ops-brain'")
    expect(WORKBENCH_HOME).toContain("'evopanel-ops-brain'")
    expect(WORKBENCH_HOME).toContain("navigate('/chat')")
    expect(WORKBENCH_HOME).toContain("sessionStorage.setItem('ef-from-ops-brain', '1')")
    expect(WORKBENCH_HOME).toMatch(/addEventListener\('message'/)
    expect(WORKBENCH_HOME).toMatch(/removeEventListener\('message'/)
    expect(WORKBENCH_HOME).toMatch(/workbench\\.kll666\\.cn/)
    expect(WORKBENCH_HOME).toContain('frame.contentWindow')
  })

  it('draft 校验：sanitizeOpsBrainDraft 只收字符串、剥 HTML、截断 ≤2k（ops-bot-mode 单实现，workbench-home 复用）', () => {
    expect(OPS_BOT_MODE).toContain('export function sanitizeOpsBrainDraft')
    expect(OPS_BOT_MODE).toMatch(/typeof raw\.text !== 'string'/)
    expect(OPS_BOT_MODE).toContain('/<[^>]*>/g') // 剥 HTML 标签
    expect(OPS_BOT_MODE).toMatch(/slice\(0,\s*2000\)/)
    expect(WORKBENCH_HOME).toContain('sanitizeOpsBrainDraft(data.draft)')
    expect(WORKBENCH_HOME).toMatch(/data\.draft\?\.urgency === 'urgent'/)
  })

  it('未知字段忽略（向前兼容）：payload 不整包透传 / 不 spread', () => {
    expect(WORKBENCH_HOME).not.toMatch(/\.\.\.data/)
    expect(WORKBENCH_HOME).not.toMatch(/Object\.assign\(\{\},\s*data/)
  })

  it('ui 缺省也进 bot-mode（兼容旧无参调用方）', () => {
    expect(WORKBENCH_HOME).toMatch(/enterOpsBotMode\(draftText \? \{ draftText, urgency \} : \{\}\)/)
  })
})

describe('1.4.10 预填不自动发（P0-3 硬安全）', () => {
  it('预填链路源码不含发送/调模型/建单/扣费调用（workbench-home / ops-bot-mode / apply-draft / shell-listeners）', () => {
    const sources = [WORKBENCH_HOME, OPS_BOT_MODE, APPLY_DRAFT, SHELL_LISTENERS]
    for (const src of sources) {
      expect(src).not.toMatch(/handleSend/)
      expect(src).not.toMatch(/invokeModel/)
      expect(src).not.toMatch(/createTicket/)
      expect(src).not.toMatch(/charge\(/)
      expect(src).not.toMatch(/autoSend/)
    }
  })

  it('apply-pending-ops-bot-draft：唯一出口是 pushComposerText（写输入框），消费即删 key', () => {
    expect(APPLY_DRAFT).toContain("'evopanel_pending_ops_bot_draft'")
    expect(APPLY_DRAFT).toContain('sessionStorage.removeItem')
    expect(APPLY_DRAFT).toMatch(/pushComposerText\(text\)/)
    expect(APPLY_DRAFT).not.toMatch(/\.(send|submit|invoke|run)\s*\(/)
  })

  it('ChatApp 两侧消费：挂载 effect + chat-route-shown（常驻补消费）', () => {
    expect(CONTROLLER).toMatch(/applyPendingOpsBotDraftImpl\(pushComposerText\)/)
    expect(SHELL_LISTENERS).toMatch(/applyPendingOpsBotDraft\(pushComposerText\)/)
    expect(SHELL_LISTENERS).toContain('pushComposerText')
  })
})

describe('1.4.10 bot-mode 双态（P0-1 / P0-5）', () => {
  it('表现态：#app.evopanel-bot-mode class + ef-ops-bot-mode 标记', () => {
    expect(OPS_BOT_MODE).toContain("'ef-ops-bot-mode'")
    expect(OPS_BOT_MODE).toMatch(/classList\.toggle\('evopanel-bot-mode'/)
  })

  it('专员态顶条：运营大脑 + 自绘 SVG 头像 + 更多运营能力控件（不引第三方 IP）', () => {
    expect(OPS_BOT_MODE).toContain("setAttribute('data-testid', 'ops-bot-strip')")
    expect(OPS_BOT_MODE).toContain('>运营大脑</span>')
    expect(OPS_BOT_MODE).toContain('data-testid="ops-bot-more-ops"')
    expect(OPS_BOT_MODE).toContain('更多运营能力')
    expect(OPS_BOT_MODE).toContain('<linearGradient')
    expect(OPS_BOT_MODE).not.toMatch(/lucide|lottie/i)
  })

  it('安全文案（P0-5）：发送前不会扣费 + 涉及花钱/真派会再问你（输入区小字）', () => {
    expect(OPS_BOT_MODE).toContain('发送前不会扣费')
    expect(OPS_BOT_MODE).toContain('涉及花钱/真派会再问你')
  })

  it('urgency 仅标签：ef-ops-bot-urgency 徽标，不建单', () => {
    expect(OPS_BOT_MODE).toContain("'ef-ops-bot-urgency'")
    expect(OPS_BOT_MODE).toContain('加急')
  })

  it('CSS：bot-mode 折叠会话列表噪音；与 workbench-mode 互斥；顶条默认隐藏', () => {
    expect(LAYOUT_CSS).toMatch(/#app\.evopanel-bot-mode #shell-chat-panel\s*\{[\s\S]*?display: none !important/)
    expect(LAYOUT_CSS).toMatch(/#app\.evopanel-bot-mode #ops-bot-strip\s*\{[\s\S]*?display: flex/)
    expect(LAYOUT_CSS).toMatch(/#app\.evopanel-workbench-mode #ops-bot-strip\s*\{[\s\S]*?display: none !important/)
    expect(LAYOUT_CSS).toMatch(/^#ops-bot-strip \{\s*\n\s*display: none;/m)
  })

  it('生命周期：离开 chat 表面自动退出（hashchange sync）；冷启恢复', () => {
    expect(OPS_BOT_MODE).toContain("window.addEventListener('hashchange', sync)")
    // 1.4.13：空 hash 兜底统一 /chat（默认 Bot 精简面）；离开 chat 仍自动退出
    expect(OPS_BOT_MODE).toMatch(/if \(!isChatSurfacePath\(location\.hash\.slice\(1\) \|\| '\/chat'\)\)/)
    expect(OPS_BOT_MODE).toMatch(/exitOpsBotMode\(\)/)
  })

  it('main.js 启动 initOpsBotMode（顶条挂载 + 路由同步）', () => {
    expect(MAIN_JS).toContain('initOpsBotMode')
  })
})

describe('1.4.10 回归：1.4.9 回工作台 / 1.4.8 顶空条不回退', () => {
  it('aside 置顶「回工作台」品牌色入口仍在（nav-workbench-home）', () => {
    expect(SHELL_ASIDE).toContain('data-testid="nav-workbench-home"')
    expect(SHELL_ASIDE).toContain('shell-nav-back-workbench')
    expect(SHELL_ASIDE).toContain('>回工作台<')
  })

  it('workbench-mode 藏 #tauri-main-chrome 仍在（无顶空条）', () => {
    expect(LAYOUT_CSS).toMatch(
      /#app\.evopanel-workbench-mode #tauri-main-chrome\s*\{[\s\S]*?display: none !important/,
    )
  })

  it('VERSION == 1.4.14（侧栏运营大脑回程入口）', () => {
    expect(VERSION).toBe('1.4.14')
  })
})
