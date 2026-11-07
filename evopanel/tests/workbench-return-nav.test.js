import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

// vitest 的 root 即 evopanel/（见 workbench-mode-shell.test.js 同款注释）
const ROOT = process.cwd()
const SHELL_ASIDE = readFileSync(join(ROOT, 'src/components/shell-aside.js'), 'utf8')
const INDEX_HTML = readFileSync(join(ROOT, 'index.html'), 'utf8')
const CHAT_BACK_HINT = readFileSync(join(ROOT, 'src/components/chat-back-hint.js'), 'utf8')
const MAIN_JS = readFileSync(join(ROOT, 'src/main.js'), 'utf8')
const WORKBENCH_HOME = readFileSync(join(ROOT, 'src/pages/workbench-home.js'), 'utf8')
const LAYOUT_CSS = readFileSync(join(ROOT, 'src/style/layout.css'), 'utf8')
const PAGES_CSS = readFileSync(join(ROOT, 'src/style/pages.css'), 'utf8')
const WORKSPACE_CSS = readFileSync(join(ROOT, 'src/style/enterprise-workspace.css'), 'utf8')
const TAURI_TITLEBAR = readFileSync(join(ROOT, 'src/lib/tauri-titlebar.js'), 'utf8')
const ROUTER = readFileSync(join(ROOT, 'src/router.js'), 'utf8')
const VERSION = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim()

describe('1.4.9 回工作台去重：侧栏唯一回程，置顶 + 品牌色（Q2-A）', () => {
  it('aside 主导航含「回工作台」+ nav-workbench-home + /workbench-home', () => {
    expect(SHELL_ASIDE).toContain('data-shell-nav="/workbench-home"')
    expect(SHELL_ASIDE).toContain('data-testid="nav-workbench-home"')
    expect(SHELL_ASIDE).toContain('>回工作台<')
    expect(SHELL_ASIDE).toMatch(/title="回工作台首页（\/workbench-home[^"]*）"/)
  })

  it('「回工作台」置顶：主导航第一项（先于驾驶舱 / 生产工单），且带品牌色 class', () => {
    const mainNav = SHELL_ASIDE.match(
      /react-chat-aside-primary[\s\S]*?shell-aside-nav-more"/,
    )?.[0] ?? ''
    expect(mainNav).toContain('data-testid="nav-workbench-home"')
    expect(mainNav).toMatch(
      /react-chat-aside-nav-item shell-nav-back-workbench" data-shell-nav="\/workbench-home"/,
    )
    const order = mainNav.match(
      /data-shell-nav="(\/workbench-home|\/chat|\/extensions\/ecom-ops-board)"/g,
    ) ?? []
    expect(order).toEqual([
      'data-shell-nav="/workbench-home"',
      'data-shell-nav="/chat"',
      'data-shell-nav="/extensions/ecom-ops-board"',
    ])
    // 置顶项后跟轻 divider，与后续常规导航分组
    const wbIdx = mainNav.indexOf('data-testid="nav-workbench-home"')
    const chatIdx = mainNav.indexOf('data-shell-nav="/chat"')
    expect(mainNav.slice(wbIdx, chatIdx)).toContain('shell-aside-nav-divider')
    const moreBody = SHELL_ASIDE.match(/id="shell-nav-more-body"[\s\S]*?<\/div>/)?.[0] ?? ''
    expect(moreBody).not.toContain('nav-workbench-home')
  })

  it('图标精致化：backWorkbench 细线复合（回程箭头 + 2×2 面板），弃 lucide image', () => {
    const btn =
      SHELL_ASIDE.match(/data-testid="nav-workbench-home"[\s\S]*?<\/button>/)?.[0] ?? ''
    expect(btn).toContain("_lucide('backWorkbench')")
    expect(btn).not.toContain("_lucide('image')")
    // ICONS 键存在且为细线复合：回程箭头杆（与面板横隔同轴 y=12）+ 圆角面板外框 + 十字分格
    const def = SHELL_ASIDE.match(/backWorkbench:\s*'([^']*)'/)?.[1] ?? ''
    expect(def).not.toBe('')
    expect(def).toContain('<path d="M10 12H4"')
    expect(def).toContain('<path d="m9 7-5 5 5 5"/>')
    expect(def).toMatch(/<rect x="12" y="5" width="9" height="14" rx="2"\/>/)
    expect(def).toContain('<path d="M16.5 5v14"')
    expect(def).toContain('<path d="M12 12h9"')
    // 纯细线，无粗填色块
    expect(def).not.toMatch(/fill=/)
  })

  it('品牌色 CSS：蓝字 + 浅蓝底，hover/active 更强（enterprise-workspace.css）', () => {
    expect(WORKSPACE_CSS).toMatch(
      /\.react-chat-aside-primary \.react-chat-aside-nav-item\.shell-nav-back-workbench \{/,
    )
    expect(WORKSPACE_CSS).toMatch(
      /\.react-chat-aside-nav-item\.shell-nav-back-workbench(:hover|\.active)/,
    )
    expect(WORKSPACE_CSS).toMatch(/--accent, #2563eb/)
  })
})

describe('1.4.9 回工作台去重：#/chat 顶栏薄条整段撤掉（P0 去重）', () => {
  it('chat-return-bar.js 已删；index.html / pages.css / main.js 无 shell-chat-return-* 残留', () => {
    expect(existsSync(join(ROOT, 'src/components/chat-return-bar.js'))).toBe(false)
    expect(INDEX_HTML).not.toContain('shell-chat-return')
    expect(INDEX_HTML).not.toContain('← 回工作台')
    expect(PAGES_CSS).not.toContain('shell-chat-return')
    expect(MAIN_JS).not.toContain('initChatReturnBar')
  })

  it('main.js 启动即 initChatBackHint（一次侧栏引导）；toast 文案指向侧栏、不再提「上方」', () => {
    expect(MAIN_JS).toContain('initChatBackHint')
    expect(CHAT_BACK_HINT).toContain("const OPS_BRAIN_FLAG = 'ef-from-ops-brain'")
    expect(CHAT_BACK_HINT).toContain('ef-chat-back-hint-shown')
    const toastText = CHAT_BACK_HINT.match(/toast\('([^']+)'/)?.[1] ?? ''
    expect(toastText).toContain('左侧')
    expect(toastText).not.toContain('上方')
  })

  it('workbench-home ops-brain 切入链路不回退：postMessage 接听 + ef-from-ops-brain 标记 + navigate(/chat)', () => {
    expect(WORKBENCH_HOME).toContain("sessionStorage.setItem('ef-from-ops-brain', '1')")
    expect(WORKBENCH_HOME).toContain("'evoflow-ops-brain'")
    expect(WORKBENCH_HOME).toContain("navigate('/chat')")
  })
})

describe('1.4.8 顶空条回归（不回退）：workbench-mode 藏 tauri-main-chrome', () => {
  it('layout.css：#app.evopanel-workbench-mode 下 #tauri-main-chrome display:none !important', () => {
    const block = LAYOUT_CSS.match(
      /#app\.evopanel-workbench-mode #tauri-main-chrome \{([\s\S]*?)\n\}/,
    )?.[1] ?? ''
    expect(block).toContain('display: none !important')
  })

  it('tauri-titlebar hide 列表含 workbench-home；router 仍调 refreshTauriMainChromeVisibility', () => {
    expect(TAURI_TITLEBAR).toMatch(/path === '\/workbench-home'/)
    expect(ROUTER).toMatch(/setWorkbenchShellMode/)
    expect(ROUTER).toMatch(/refreshTauriMainChromeVisibility/)
  })

  it('VERSION == 1.4.9', () => {
    expect(VERSION).toBe('1.4.9')
  })
})
