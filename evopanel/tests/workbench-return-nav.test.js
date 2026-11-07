import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// vitest 的 root 即 evopanel/（见 workbench-mode-shell.test.js 同款注释）
const ROOT = process.cwd()
const SHELL_ASIDE = readFileSync(join(ROOT, 'src/components/shell-aside.js'), 'utf8')
const INDEX_HTML = readFileSync(join(ROOT, 'index.html'), 'utf8')
const CHAT_RETURN_BAR = readFileSync(join(ROOT, 'src/components/chat-return-bar.js'), 'utf8')
const MAIN_JS = readFileSync(join(ROOT, 'src/main.js'), 'utf8')
const WORKBENCH_HOME = readFileSync(join(ROOT, 'src/pages/workbench-home.js'), 'utf8')
const LAYOUT_CSS = readFileSync(join(ROOT, 'src/style/layout.css'), 'utf8')
const PAGES_CSS = readFileSync(join(ROOT, 'src/style/pages.css'), 'utf8')
const VERSION = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim()

describe('1.4.8 回工作台：侧栏显性回程（P0-a）', () => {
  it('aside 主导航含「回工作台」+ nav-workbench-home + /workbench-home，且不再叫「电商图片」', () => {
    expect(SHELL_ASIDE).toContain('data-shell-nav="/workbench-home"')
    expect(SHELL_ASIDE).toContain('data-testid="nav-workbench-home"')
    expect(SHELL_ASIDE).toContain('>回工作台<')
    expect(SHELL_ASIDE).toMatch(/title="回工作台首页（\/workbench-home[^"]*）"/)
    expect(SHELL_ASIDE).not.toContain('>电商图片<')
  })

  it('「回工作台」上移到主导航（生产工单之后），不再藏在 Agent应用 所在的「更多」组', () => {
    const mainNav = SHELL_ASIDE.match(
      /react-chat-aside-primary[\s\S]*?shell-aside-nav-more"/,
    )?.[0] ?? ''
    expect(mainNav).toContain('data-testid="nav-workbench-home"')
    const moreBody = SHELL_ASIDE.match(/id="shell-nav-more-body"[\s\S]*?<\/div>/)?.[0] ?? ''
    expect(moreBody).not.toContain('nav-workbench-home')
  })

  it('上移位置：紧随生产工单（驾驶舱 → 生产工单 → 回工作台）', () => {
    const order = SHELL_ASIDE.match(
      /data-shell-nav="(\/chat|\/extensions\/ecom-ops-board|\/workbench-home)"/g,
    ) ?? []
    expect(order).toEqual([
      'data-shell-nav="/chat"',
      'data-shell-nav="/extensions/ecom-ops-board"',
      'data-shell-nav="/workbench-home"',
    ])
  })
})

describe('1.4.8 回工作台：#/chat 显性控件 + 一次引导（P0-b）', () => {
  it('index.html：#chat-persistent-host 之前有回程薄栏，文案「回工作台」', () => {
    expect(INDEX_HTML).toContain('id="shell-chat-return-bar"')
    expect(INDEX_HTML).toContain('id="shell-chat-return-btn"')
    expect(INDEX_HTML).toContain('← 回工作台')
    expect(INDEX_HTML.indexOf('shell-chat-return-bar')).toBeLessThan(
      INDEX_HTML.indexOf('id="chat-persistent-host"'),
    )
  })

  it('chat-return-bar.js：click → navigate(/workbench-home)；toast 双 sessionStorage 键防刷屏', () => {
    expect(CHAT_RETURN_BAR).toContain("navigate('/workbench-home')")
    expect(CHAT_RETURN_BAR).toContain("'ef-from-ops-brain'")
    expect(CHAT_RETURN_BAR).toContain("'ef-opsbrain-toast-shown'")
    expect(CHAT_RETURN_BAR).toMatch(/addEventListener\('hashchange'/)
  })

  it('main.js 启动即 initChatReturnBar；workbench-home ops-brain 切入打 ef-from-ops-brain 标记', () => {
    expect(MAIN_JS).toContain('initChatReturnBar')
    expect(WORKBENCH_HOME).toContain("sessionStorage.setItem('ef-from-ops-brain', '1')")
    // 1.4.7 既有能力不回退：postMessage 接听仍在
    expect(WORKBENCH_HOME).toContain("'evoflow-ops-brain'")
    expect(WORKBENCH_HOME).toContain("navigate('/chat')")
  })

  it('pages.css：薄栏默认隐藏，仅 #chat-persistent-host 可见（:has 门控）时显示', () => {
    expect(PAGES_CSS).toContain('.shell-chat-return-bar')
    expect(PAGES_CSS).toMatch(
      /#main-col:has\(> #chat-persistent-host:not\(\[hidden\]\)\) \.shell-chat-return-bar/,
    )
  })
})

describe('1.4.8 顶栏裁切修复：workbench-mode #content 成为 abs host 包含块', () => {
  it('layout.css：#content 补 position:relative / overflow / flex 列', () => {
    const block = LAYOUT_CSS.match(
      /#app\.evopanel-workbench-mode #content \{([\s\S]*?)\n\}/,
    )?.[1] ?? ''
    expect(block).toContain('position: relative')
    expect(block).toContain('overflow: hidden')
    expect(block).toContain('display: flex')
    expect(block).toContain('flex-direction: column')
  })

  it('layout.css：workbench-mode 藏 #update-banner / #gw-banner（仿 kb-detail，防挤高）', () => {
    expect(LAYOUT_CSS).toMatch(/evopanel-workbench-mode #update-banner/)
    expect(LAYOUT_CSS).toMatch(/evopanel-workbench-mode #gw-banner/)
  })

  it('VERSION == 1.4.8', () => {
    expect(VERSION).toBe('1.4.8')
  })
})
