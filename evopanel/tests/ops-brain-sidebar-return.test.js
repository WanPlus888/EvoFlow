/**
 * 运营大脑侧栏回程入口（1.4.14）回归：
 * - 侧栏「回工作台」正下方钉常驻「运营大脑」项（nav-ops-brain，全壳页可见）
 * - 点击 = 清 ef-ops-bot-exited（reenterOpsBotMode）+ enterOpsBotMode + navigate('/chat')
 * - 「更多运营能力」仍 exitOpsBotMode + 写 exited；「回工作台」行为不变
 * - bot-mode CSS 不藏 aside 导航（新入口在 bot-mode 与全壳均可达）
 * 源码断言风格与 workbench-return-nav / ops-bot-mode 一致。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// vitest 的 root 即 evopanel/（见 workbench-mode-shell.test.js 同款注释）
const ROOT = process.cwd()
const SHELL_ASIDE = readFileSync(join(ROOT, 'src/components/shell-aside.js'), 'utf8')
const OPS_BOT_MODE = readFileSync(join(ROOT, 'src/components/ops-bot-mode.js'), 'utf8')
const WORKSPACE_CSS = readFileSync(join(ROOT, 'src/style/enterprise-workspace.css'), 'utf8')
const LAYOUT_CSS = readFileSync(join(ROOT, 'src/style/layout.css'), 'utf8')
const VERSION = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim()

describe('1.4.14 侧栏「运营大脑」常驻项：回工作台正下方、不进「更多」折叠区', () => {
  it('aside 主导航含「运营大脑」+ nav-ops-brain + 专用 data-act（非通用 data-shell-nav）', () => {
    expect(SHELL_ASIDE).toContain('data-testid="nav-ops-brain"')
    expect(SHELL_ASIDE).toContain('>运营大脑<')
    const btn = SHELL_ASIDE.match(/<button[^>]*data-testid="nav-ops-brain"[\s\S]*?<\/button>/)?.[0] ?? ''
    expect(btn).toContain('data-act="enter-ops-brain"')
    // 不走通用 data-shell-nav="/chat"：那是驾驶舱全壳态，不清 exited、不进 bot-mode
    expect(btn).not.toContain('data-shell-nav')
    expect(btn).toMatch(/title="运营大脑（Bot 聊天）"/)
  })

  it('顺序钉死：回工作台 → 运营大脑 → 驾驶舱（nav-ops-brain 不落「更多」折叠区）', () => {
    const wbIdx = SHELL_ASIDE.indexOf('data-testid="nav-workbench-home"')
    const obIdx = SHELL_ASIDE.indexOf('data-testid="nav-ops-brain"')
    const chatIdx = SHELL_ASIDE.indexOf('data-shell-nav="/chat"')
    expect(wbIdx).toBeGreaterThan(-1)
    expect(obIdx).toBeGreaterThan(wbIdx)
    expect(chatIdx).toBeGreaterThan(obIdx)
    const moreBody = SHELL_ASIDE.match(/id="shell-nav-more-body"[\s\S]*?<\/div>/)?.[0] ?? ''
    expect(moreBody).not.toContain('nav-ops-brain')
  })
})

describe('1.4.14 点击路径：清 exited + 强制 enter + 路由 /chat（同 hash 不短路）', () => {
  it('shell-aside 专用分支：closest(data-act) → reenterOpsBotMode() + navigate(/chat)', () => {
    expect(SHELL_ASIDE).toContain("reenterOpsBotMode()")
    expect(SHELL_ASIDE).toContain("navigate('/chat')")
    // 专用分支在侧栏 click 委托内，且先于通用 data-shell-nav 分支
    expect(SHELL_ASIDE).toMatch(/closest\('\[data-act="enter-ops-brain"\]'\)/)
    const actIdx = SHELL_ASIDE.indexOf("closest('[data-act=\"enter-ops-brain\"]')")
    const navIdx = SHELL_ASIDE.indexOf("closest('[data-shell-nav]')")
    expect(actIdx).toBeGreaterThan(-1)
    expect(navIdx).toBeGreaterThan(actIdx)
  })

  it('reenterOpsBotMode 导出：显式清 exited 标记再 enterOpsBotMode（与冷启策略兼容）', () => {
    expect(OPS_BOT_MODE).toMatch(/export function reenterOpsBotMode/)
    const fn = OPS_BOT_MODE.match(/export function reenterOpsBotMode[\s\S]*?\n\}/)?.[0] ?? ''
    expect(fn).toContain('removeItem(BOT_MODE_EXITED_FLAG)')
    expect(fn).toContain('enterOpsBotMode()')
    // shell-aside 从 ops-bot-mode 复用 helper，而非自写 sessionStorage 直改
    expect(SHELL_ASIDE).toMatch(/import \{ reenterOpsBotMode \} from '\.\/ops-bot-mode\.js'/)
  })

  it('进 bot 仍清 exited、退出仍写 exited（1.4.13 冷启默认 Bot 语义不回退）', () => {
    expect(OPS_BOT_MODE).toMatch(/sessionStorage\.removeItem\(BOT_MODE_EXITED_FLAG\)/)
    expect(OPS_BOT_MODE).toMatch(/sessionStorage\.setItem\(BOT_MODE_EXITED_FLAG, '1'\)/)
    expect(OPS_BOT_MODE).toMatch(/if \(!entered && !exited && isChatSurfacePath/)
  })
})

describe('1.4.14 回归：「更多运营能力」退出 / 「回工作台」回程均不变', () => {
  it('「更多运营能力」仍就地 exitOpsBotMode（不删不改名）', () => {
    expect(OPS_BOT_MODE).toContain('更多运营能力')
    expect(OPS_BOT_MODE).toMatch(/ops-bot-more.*exitOpsBotMode/s)
    expect(OPS_BOT_MODE).toContain("window.addEventListener('hashchange', sync)")
  })

  it('「回工作台」仍 data-shell-nav="/workbench-home" + nav-workbench-home + 品牌蓝', () => {
    expect(SHELL_ASIDE).toContain('data-shell-nav="/workbench-home"')
    expect(SHELL_ASIDE).toContain('data-testid="nav-workbench-home"')
    expect(SHELL_ASIDE).toContain('>回工作台<')
    expect(WORKSPACE_CSS).toMatch(
      /\.react-chat-aside-primary \.react-chat-aside-nav-item\.shell-nav-back-workbench \{/,
    )
  })
})

describe('1.4.14 样式与显隐：紫系次级强调；bot-mode 不藏侧栏导航', () => {
  it('enterprise-workspace.css 含 shell-nav-ops-brain 块（紫 #7c5cf0 系，非回工作台蓝）', () => {
    expect(WORKSPACE_CSS).toMatch(
      /\.react-chat-aside-primary \.react-chat-aside-nav-item\.shell-nav-ops-brain \{/,
    )
    expect(WORKSPACE_CSS).toMatch(/\.shell-nav-ops-brain(:hover|\.active)/)
    const obBlock = WORKSPACE_CSS.match(/\.shell-nav-ops-brain \{[\s\S]*?\n\}/)?.[0] ?? ''
    expect(obBlock).toContain('#7c5cf0')
    expect(obBlock).not.toContain('2563eb')
  })

  it('bot-mode 只折叠会话列表（#shell-chat-panel），无规则隐藏 aside 主导航', () => {
    expect(LAYOUT_CSS).toMatch(/#app\.evopanel-bot-mode #shell-chat-panel\s*\{[\s\S]*?display: none !important/)
    expect(LAYOUT_CSS).not.toMatch(/evopanel-bot-mode[^{}]*react-chat-aside-primary/)
    expect(WORKSPACE_CSS).not.toMatch(/evopanel-bot-mode[^{}]*react-chat-aside-primary/)
  })
})

describe('1.4.14 禁区：零千川生产写符号；VERSION', () => {
  it('本刀源码不含 qianchuan / oceanengine 生产写链', () => {
    for (const src of [SHELL_ASIDE, OPS_BOT_MODE, WORKSPACE_CSS]) {
      expect(src).not.toMatch(/qianchuan|oceanengine|ocean_engine/i)
    }
  })

  it('VERSION == 1.4.15（1.4.15 登录统一刀 bump）', () => {
    expect(VERSION).toBe('1.4.15')
  })
})
