/**
 * 运营大脑侧栏回程入口（1.4.14）回归：
 * - 侧栏「回工作台」正下方钉常驻「运营大脑」项（nav-ops-brain，全壳页可见）
 * - 点击 = 清 ef-ops-bot-exited（reenterOpsBotMode）+ enterOpsBotMode + navigate('/chat')
 * - 「更多运营能力」仍 exitOpsBotMode + 写 exited；「回工作台」行为不变
 * - bot-mode CSS 不藏 aside 导航（新入口在 bot-mode 与全壳均可达）
 * 1.4.16 回程离开驾驶舱首页（补刀）：
 * - 回程分支在 reenter + navigate 后补发 evopanel:ops-brain-reenter（同 hash 无 hashchange，
 *   只靠 navigate 不离开 preferHomeDashboard 驾驶舱首页）
 * - handleOpenHome 清空 sessionKey 前记 ef-ops-bot-last-session；reenter 监听清首页意图
 *   并恢复上一会话，兜底空白聊天（绝不 handleOpenHome 回驾驶舱）
 * - 行为测例：真实跑 runShellWindowListenersEffect 派发事件验证状态迁移
 * 源码断言风格与 workbench-return-nav / ops-bot-mode 一致。
 */
import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { runShellWindowListenersEffect } from '../src/react/chat-app/shell/install-shell-window-listeners.ts'

// vitest 的 root 即 evopanel/（见 workbench-mode-shell.test.js 同款注释）
const ROOT = process.cwd()
const SHELL_ASIDE = readFileSync(join(ROOT, 'src/components/shell-aside.js'), 'utf8')
const OPS_BOT_MODE = readFileSync(join(ROOT, 'src/components/ops-bot-mode.js'), 'utf8')
const WORKSPACE_CSS = readFileSync(join(ROOT, 'src/style/enterprise-workspace.css'), 'utf8')
const LAYOUT_CSS = readFileSync(join(ROOT, 'src/style/layout.css'), 'utf8')
const SHELL_LISTENERS = readFileSync(
  join(ROOT, 'src/react/chat-app/shell/install-shell-window-listeners.ts'),
  'utf8',
)
const CONTROLLER = readFileSync(join(ROOT, 'src/react/chat-app/use-chat-app-controller.tsx'), 'utf8')
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

describe('1.4.16 回程离开驾驶舱首页：事件链（源码断言）', () => {
  it('enter-ops-brain 分支：reenterOpsBotMode + navigate(/chat) 后派发 evopanel:ops-brain-reenter', () => {
    const branch = SHELL_ASIDE.match(/if \(opsBrainBtn\) \{[\s\S]*?\n    \}/)?.[0] ?? ''
    expect(branch).toContain('reenterOpsBotMode()')
    expect(branch).toContain("navigate('/chat')")
    expect(branch).toContain('evopanel:ops-brain-reenter')
    // 派发必须存在且不早于 navigate（navigate 同 hash 无事件，补刀事件负责离开首页）
    expect(branch.indexOf("navigate('/chat')")).toBeLessThan(branch.indexOf('evopanel:ops-brain-reenter'))
  })

  it('handleOpenHome：清空 sessionKey 之前记 ef-ops-bot-last-session（回程恢复依据）', () => {
    const fn = CONTROLLER.match(/function handleOpenHome\(\) \{[\s\S]*?\n  \}/)?.[0] ?? ''
    expect(fn).toContain("'ef-ops-bot-last-session'")
    expect(fn.indexOf('const oldSk')).toBeLessThan(fn.indexOf("'ef-ops-bot-last-session'"))
    expect(fn.indexOf("'ef-ops-bot-last-session'")).toBeLessThan(fn.indexOf("setSelectedSessionKey('')"))
  })

  it('reenter 监听：清 preferHome → last-session 恢复 / 已有会话 no-op / 兜底新会话；绝不 handleOpenHome', () => {
    expect(SHELL_LISTENERS).toContain("'evopanel:ops-brain-reenter'")
    const fn = SHELL_LISTENERS.match(/const onOpsBrainReenter = \(\) => \{[\s\S]*?\n    \}/)?.[0] ?? ''
    expect(fn).toContain('preferHomeDashboardRef.current = false')
    expect(fn).toContain('setPreferHomeDashboard?.(false)')
    expect(fn).toContain("'ef-ops-bot-last-session'")
    expect(fn).toContain('selectSessionFromShellRef.current(lastSession)')
    expect(fn).toContain('handleNewSessionRef.current?.()')
    // 回程绝不把用户再送回驾驶舱首页
    expect(fn).not.toContain('handleOpenHomeRef')
    // add/removeEventListener 对称注册（无泄漏）
    expect(SHELL_LISTENERS).toMatch(/addEventListener\('evopanel:ops-brain-reenter', onOpsBrainReenter\)/)
    expect(SHELL_LISTENERS).toMatch(/removeEventListener\('evopanel:ops-brain-reenter', onOpsBrainReenter\)/)
  })

  it('controller ctx 接线：preferHomeDashboardRef / sessionRef / setPreferHomeDashboard 传入监听 effect', () => {
    const call = CONTROLLER.match(/runShellWindowListenersEffect\(\{[\s\S]*?\n    \}\)/)?.[0] ?? ''
    expect(call).toContain('preferHomeDashboardRef')
    expect(call).toContain('sessionRef')
    expect(call).toContain('setPreferHomeDashboard')
  })

  it('reenterOpsBotMode 注释写明边界：单靠它 + navigate 不会离开首页仪表盘', () => {
    const doc = OPS_BOT_MODE.match(/\/\*\*[\s\S]*?export function reenterOpsBotMode/)?.[0] ?? ''
    expect(doc).toContain('evopanel:ops-brain-reenter')
    expect(doc).toContain('不会离开首页仪表盘')
  })
})

describe('1.4.16 行为测例：preferHome=true 停在驾驶舱首页时派发 reenter 事件', () => {
  function setupListeners() {
    const state = {
      preferHomeDashboardRef: { current: true },
      setPreferHomeDashboard: vi.fn(),
      sessionRef: { current: '' },
      selectSessionFromShell: vi.fn(),
      handleNewSession: vi.fn(),
      handleOpenHome: vi.fn(),
    }
    const cleanup = runShellWindowListenersEffect({
      cancelPendingStreamUiBumpsRef: { current: () => {} },
      handleNewSessionRef: { current: state.handleNewSession },
      handleOpenHomeRef: { current: state.handleOpenHome },
      isChatOverlayDeferActive: () => false,
      openCollabExecPanel: vi.fn(),
      preferHomeDashboardRef: state.preferHomeDashboardRef,
      pushComposerText: vi.fn(),
      reviveAllTurnBusyIfLivePostOpen: vi.fn(),
      scheduleBumpRef: { current: vi.fn() },
      selectSessionFromShellRef: { current: state.selectSessionFromShell },
      sessionRef: state.sessionRef,
      setChatSurfaceVisible: vi.fn(),
      setMobileChatPane: vi.fn(),
      setPreferHomeDashboard: state.setPreferHomeDashboard,
    })
    return { state, cleanup }
  }

  it('无 last-session + 空会话：清 preferHome + 空白新会话（handleOpenHome 绝不被调）', () => {
    sessionStorage.clear()
    const { state, cleanup } = setupListeners()
    try {
      window.dispatchEvent(new CustomEvent('evopanel:ops-brain-reenter'))
      expect(state.preferHomeDashboardRef.current).toBe(false)
      expect(state.setPreferHomeDashboard).toHaveBeenCalledWith(false)
      expect(state.handleNewSession).toHaveBeenCalledTimes(1)
      expect(state.selectSessionFromShell).not.toHaveBeenCalled()
      // 回程绝不能再触发「打开驾驶舱首页」
      expect(state.handleOpenHome).not.toHaveBeenCalled()
    } finally {
      cleanup()
    }
  })

  it('有 ef-ops-bot-last-session：恢复上一会话，不开新会话', () => {
    sessionStorage.clear()
    sessionStorage.setItem('ef-ops-bot-last-session', 'ops-session-1024')
    const { state, cleanup } = setupListeners()
    try {
      window.dispatchEvent(new CustomEvent('evopanel:ops-brain-reenter'))
      expect(state.selectSessionFromShell).toHaveBeenCalledWith('ops-session-1024')
      expect(state.handleNewSession).not.toHaveBeenCalled()
      expect(state.preferHomeDashboardRef.current).toBe(false)
    } finally {
      cleanup()
      sessionStorage.clear()
    }
  })

  it('无记录但已在会话上：只清首页意图（no-op，不误开新会话）', () => {
    sessionStorage.clear()
    const { state, cleanup } = setupListeners()
    state.sessionRef.current = 'cur-session-7'
    try {
      window.dispatchEvent(new CustomEvent('evopanel:ops-brain-reenter'))
      expect(state.preferHomeDashboardRef.current).toBe(false)
      expect(state.setPreferHomeDashboard).toHaveBeenCalledWith(false)
      expect(state.selectSessionFromShell).not.toHaveBeenCalled()
      expect(state.handleNewSession).not.toHaveBeenCalled()
    } finally {
      cleanup()
    }
  })
})

describe('1.4.14 禁区：零千川生产写符号；VERSION', () => {
  it('本刀源码不含 qianchuan / oceanengine 生产写链', () => {
    for (const src of [SHELL_ASIDE, OPS_BOT_MODE, WORKSPACE_CSS]) {
      expect(src).not.toMatch(/qianchuan|oceanengine|ocean_engine/i)
    }
  })

  it('VERSION == 1.4.16', () => {
    expect(VERSION).toBe('1.4.16')
  })
})
