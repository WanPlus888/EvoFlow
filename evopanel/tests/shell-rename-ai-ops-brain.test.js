import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 1.4.19 应用改名回归：旧名（'电商运营' + '终端' 拼接）→ AI 运营大脑（英文 AI Ops Brain）。
 * 边界：identifier / 可执行名 / scheme / 数据目录 / 包名严禁变；
 * 功能模块名「运营大脑」（侧栏 nav-ops-brain、Bot 顶条、专员 Router）必须原样保留。
 *
 * 注：旧名在断言里用拆字拼接，避免本文件自身打中验收 grep（白名单外旧名零命中）。
 */
const ROOT = process.cwd() // vitest root = evopanel/
const LEGACY = ['电商运营', '终端'].join('')
const NEW_ZH = 'AI 运营大脑'
const NEW_EN = 'AI Ops Brain'

const read = (rel) => readFileSync(join(ROOT, rel), 'utf8')

const TAURI_CONF = JSON.parse(read('src-tauri/tauri.conf.json'))
const TAURI_MACOS_CONF = JSON.parse(read('src-tauri/tauri.macos.conf.json'))
const INDEX_HTML = read('index.html')
const TRAY_RS = read('src-tauri/src/tray.rs')
const ABOUT_JS = read('src/pages/about.js')
const LOGIN_JS = read('src/pages/login.js')
const SHELL_ASIDE = read('src/components/shell-aside.js')
const OPS_BOT_MODE = read('src/components/ops-bot-mode.js')
const OPS_SPECIALISTS = read('src/lib/ops-specialists.js')
const ZH_CN_TS = read('src/zcode-ui/i18n/locales/zh-CN.ts')
const EN_US_TS = read('src/zcode-ui/i18n/locales/en-US.ts')

describe('1.4.19 应用改名 · 配置层', () => {
  it('tauri.conf.json productName / 窗口 title / bundle 描述 = AI 运营大脑', () => {
    expect(TAURI_CONF.productName).toBe(NEW_ZH)
    expect(TAURI_CONF.app.windows[0].title).toBe(NEW_ZH)
    expect(TAURI_CONF.bundle.shortDescription).toContain(NEW_ZH)
    expect(TAURI_CONF.bundle.longDescription).toContain(NEW_ZH)
    // PolyForm Required Notice：归属保留上游真名 EvoFlow，且不得再嵌旧名双写
    expect(TAURI_CONF.bundle.longDescription).toContain('基于 EvoFlow（EvovexAI')
    expect(TAURI_CONF.bundle.longDescription).not.toContain(LEGACY)
    // 版本钉随刀抬：壳合入刀（1419 改名 + 1420 硬化）交付 1.4.20
    expect(TAURI_CONF.version).toBe('1.4.20')
  })

  it('身份标识严禁改：identifier / 可执行 / scheme / 数据根保持 evoflow 系', () => {
    expect(TAURI_CONF.identifier).toBe('com.evovex.evoflow')
    // Cargo [[bin]] 与 package 名不动（可执行仍为 evoflow / 包名 evopanel）
    const cargoToml = read('src-tauri/Cargo.toml')
    expect(cargoToml).toMatch(/^\s*name = "evopanel"$/m)
    expect(cargoToml).not.toMatch(/^\s*name\s*=.*运营大脑/m)
    expect(TAURI_CONF.plugins.updater.endpoints[0]).toContain('evoflow-fork')
  })

  it('tauri.macos.conf.json title 同步 + index.html <title> 与启动台品牌名', () => {
    expect(TAURI_MACOS_CONF.app.windows[0].title).toBe(NEW_ZH)
    expect(INDEX_HTML).toMatch(new RegExp(`<title>${NEW_ZH}</title>`))
    // 启动台左上角品牌名（上代漏网的上游 EvoFlow 残留）→ 新名
    expect(INDEX_HTML).toContain(`class="boot-console__name">${NEW_ZH}</span>`)
    expect(INDEX_HTML).not.toContain(`boot-console__name">EvoFlow</span>`)
  })
})

describe('1.4.19 应用改名 · 托盘与前端品牌', () => {
  it('tray.rs 无用户可见 EvoFlow 残留：退出菜单 / tooltip / 空 tip 默认', () => {
    expect(TRAY_RS).toContain(`"quit", "退出 ${NEW_ZH}"`)
    expect(TRAY_RS).toContain(`.tooltip("${NEW_ZH} · 待命`)
    expect(TRAY_RS).toContain(`if tip.is_empty() { "${NEW_ZH}" }`)
    expect(TRAY_RS).not.toContain('退出 EvoFlow')
    expect(TRAY_RS).not.toContain('EvoFlow · 待命')
    expect(TRAY_RS).not.toContain('{ "EvoFlow" }')
    // 事件名等非品牌标识不动
    expect(TRAY_RS).toContain('evoflow:open-resource-manager')
  })

  it('关于页 / 登录品牌面板含新名，无旧名', () => {
    expect(ABOUT_JS).toContain(`alt="${NEW_ZH}"`)
    expect(ABOUT_JS).toMatch(/<h2 class="about-name">[^<]*运营大脑[^<]*<\/h2>/)
    expect(LOGIN_JS).toContain(`aria-label="${NEW_ZH}"`)
    expect(LOGIN_JS).toContain('webui-login-brand-title')
    expect(LOGIN_JS).not.toContain(LEGACY)
  })

  it('侧栏品牌标题 = 新名；模块导航 nav-ops-brain 标签仍为「运营大脑」', () => {
    expect(SHELL_ASIDE).toContain(`react-chat-aside-toolbar-title">${NEW_ZH}</span>`)
    // 模块入口（data-testid="nav-ops-brain"）是功能模块名，不吃应用改名
    const navMatch = SHELL_ASIDE.match(
      /data-testid="nav-ops-brain"[^>]*title="([^"]*)"[^>]*aria-label="([^"]*)"/,
    )
    expect(navMatch).not.toBeNull()
    expect(navMatch[1]).toBe('运营大脑（Bot 聊天）')
    expect(navMatch[2]).toBe('运营大脑')
    expect(SHELL_ASIDE).toContain('<span class="react-chat-aside-nav-label">运营大脑</span>')
  })

  it('模块文案保留：Bot 顶条 / OPS_SPECIALISTS Router 名不带「AI」前缀污染', () => {
    expect(OPS_BOT_MODE).toContain('运营大脑')
    expect(OPS_BOT_MODE).not.toContain(NEW_ZH)
    expect(OPS_SPECIALISTS).toContain("name: '运营大脑'")
    expect(OPS_SPECIALISTS).not.toContain(NEW_ZH)
  })

  it('i18n 一致：zh-CN 用中文名、en-US 用英文名，两侧均无旧名', () => {
    expect(ZH_CN_TS).toContain(NEW_ZH)
    expect(EN_US_TS).toContain(NEW_EN)
    expect(EN_US_TS).not.toContain(LEGACY)
    expect(ZH_CN_TS).not.toContain(LEGACY)
  })

  it('启动层 TAGLINE / 帮助文案 / cua-glow 覆盖层无 EvoFlow 品牌残留', () => {
    const consoleUi = read('public/console/ui.js')
    expect(consoleUi).toContain(`TAGLINE = '${NEW_ZH} ——`)
    const pageHelp = read('src/lib/page-help.js')
    expect(pageHelp).toContain('`/lead` 切回 AI 运营大脑')
    expect(pageHelp).not.toContain('切回 EvoFlow')
    const cuaHtml = read('cua-glow-overlay.html') // evopanel 根
    expect(cuaHtml).toContain('AI Ops Brain Computer Use')
    expect(cuaHtml).not.toContain('EvoFlow 正在操作电脑')
  })

  it('品牌清扫零残留：品牌关键文件不出现旧名（拆字断言）', () => {
    const files = [
      'src/main.js',
      'src/components/mobile-tabbar.js',
      'src/components/sidebar.js',
      'src/components/engagement.js',
      'src/components/modal.js',
      'src/lib/desktop-notification.js',
      'src/lib/panel-login.js',
      'src/lib/background-voice.js',
      'src/lib/desktop-updater.js',
      'src/locales/zh-CN.json',
      'src/locales/en.json',
      '../backend/app/gateway/routers/ops_summary.py',
    ]
    for (const rel of files) {
      expect(read(rel), rel).not.toContain(LEGACY)
    }
  })
})
