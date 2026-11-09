import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// vitest 的 root 即 evopanel/（见 font-size-tokens.test.js 同款注释）
const ROOT = process.cwd()
const ROUTER = readFileSync(join(ROOT, 'src/router.js'), 'utf8')
const LAYOUT_CSS = readFileSync(join(ROOT, 'src/style/layout.css'), 'utf8')
const WORKBENCH_HOME = readFileSync(join(ROOT, 'src/pages/workbench-home.js'), 'utf8')
const ASSISTANT_CTX = readFileSync(
  join(ROOT, 'src/components/global-assistant/assistant-context.js'),
  'utf8',
)
const VERSION = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim()
const TITLEBAR = readFileSync(join(ROOT, 'src/lib/tauri-titlebar.js'), 'utf8')

describe('1.4.7 工作台冷启：workbench-mode 藏壳侧栏', () => {
  it('router.js 提供 isWorkbenchHomeRoute + setWorkbenchShellMode（独立 class）', () => {
    expect(ROUTER).toContain('export function isWorkbenchHomeRoute')
    expect(ROUTER).toContain('function setWorkbenchShellMode')
    expect(ROUTER).toContain("classList.toggle('evopanel-workbench-mode'")
    // 路由加载两分支都要维护该 class
    expect(ROUTER).toContain('setWorkbenchShellMode(false)')
    expect(ROUTER).toContain('setWorkbenchShellMode(isWorkbenchHomeRoute(path))')
  })

  it('workbench-home 不并入 isImmersiveShellRoute（避免 studio 副作用）', () => {
    const body = ROUTER.match(
      /export function isImmersiveShellRoute\(path\) \{([\s\S]*?)\n\}/,
    )?.[1] ?? ''
    expect(body).not.toContain('workbench')
  })

  it('layout.css 藏 aside / 展开钮，主列全幅', () => {
    expect(LAYOUT_CSS).toContain('#app.evopanel-workbench-mode #app-shell-aside')
    expect(LAYOUT_CSS).toContain('#app.evopanel-workbench-mode .shell-aside-expand-btn')
    expect(LAYOUT_CSS).toMatch(/#app\.evopanel-workbench-mode #main-col\s*\{[\s\S]*?flex: 1 1 100%/)
    // 勿藏 ops-float（运营悬浮层仍在）
    expect(LAYOUT_CSS).not.toMatch(/evopanel-workbench-mode[^{]*ops-float/)
  })

  it('workbench-home.js：ops-brain postMessage → navigate(/chat)，render 注册 / cleanup 注销', () => {
    expect(WORKBENCH_HOME).toContain("'evoflow-ops-brain'")
    expect(WORKBENCH_HOME).toContain("'evopanel-ops-brain'")
    expect(WORKBENCH_HOME).toContain("navigate('/chat')")
    expect(WORKBENCH_HOME).toMatch(/addEventListener\('message'/)
    expect(WORKBENCH_HOME).toMatch(/removeEventListener\('message'/)
    // 源校验：工作台 origin 或本页 iframe
    expect(WORKBENCH_HOME).toMatch(/workbench\\.kll666\\.cn/)
    expect(WORKBENCH_HOME).toContain('frame.contentWindow')
  })

  it('VERSION == 1.4.18（账号同步刀 bump）；shouldHideAssistant 仍藏小V（workbench-home）', () => {
    expect(VERSION).toBe('1.4.18')
    expect(ASSISTANT_CTX).toMatch(/path === 'workbench-home'/)
  })
})

describe('1.4.8 续刀：workbench-mode 藏 #tauri-main-chrome（消回程顶空条）', () => {
  it('layout.css：workbench-mode 藏壳顶带（仿 kb-detail）', () => {
    expect(LAYOUT_CSS).toMatch(
      /#app\.evopanel-workbench-mode #tauri-main-chrome\s*\{[\s\S]*?display: none !important/,
    )
  })

  it('tauri-titlebar.js：hide 条件含 workbench-home 路由与 workbench-mode class', () => {
    const body =
      TITLEBAR.match(/function syncMainChromeVisibility\(\) \{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(body).toContain("path === '/workbench-home'")
    expect(body).toContain("path === 'workbench-home'")
    expect(body).toContain('evopanel-workbench-mode')
  })

  it('router.js：setWorkbenchShellMode 即时刷新 chrome 可见性（对齐 kb-detail）', () => {
    const body = ROUTER.match(/function setWorkbenchShellMode\(active\) \{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(body).toContain('refreshTauriMainChromeVisibility')
  })

  it('回归：#content position:relative 与藏 banner 仍在（前刀不回退）', () => {
    const block = LAYOUT_CSS.match(/#app\.evopanel-workbench-mode #content \{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(block).toContain('position: relative')
    expect(LAYOUT_CSS).toMatch(/evopanel-workbench-mode #update-banner/)
    expect(LAYOUT_CSS).toMatch(/evopanel-workbench-mode #gw-banner/)
  })
})
