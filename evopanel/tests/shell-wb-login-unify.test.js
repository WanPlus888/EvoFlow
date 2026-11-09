/**
 * 壳登录统一方案1（1.4.15）回归：
 * - switch 主路径（#/login?switch=1）改调 AI 工作台账密：loginWithWorkbench
 *   → gateway 代理 POST /webui/login-workbench（服务端转 workbench /api/auth/login）
 * - Local Admin / 远程 WebUI 旁路保留：原 login() → POST /webui/login 不动；
 *   switch 页提供 ?local=1 次要入口「本机运维登录」
 * - 成功路径仍是 prepareAccountSwitch + saveAuthToken + reload（隔离不回退）
 * - 文案：users.js 不再把壳本地户宣称为侧栏切换用户的主来源
 * 源码断言风格与 ops-brain-sidebar-return / workbench-return-nav 一致。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// vitest 的 root 即 evopanel/（见 workbench-mode-shell.test.js 同款注释）
const ROOT = process.cwd()
const LOGIN_PAGE = readFileSync(join(ROOT, 'src/pages/login.js'), 'utf8')
const WEBUI_REMOTE = readFileSync(join(ROOT, 'src/lib/webui-remote.js'), 'utf8')
const ACCOUNT_SESSION = readFileSync(join(ROOT, 'src/lib/account-session.js'), 'utf8')
const SHELL_ACCOUNT = readFileSync(join(ROOT, 'src/components/shell-account.js'), 'utf8')
const USERS_SETTINGS = readFileSync(join(ROOT, 'src/pages/settings/users.js'), 'utf8')
const WORKBENCH_URLS = readFileSync(join(ROOT, 'src/lib/workbench-urls.js'), 'utf8')
const BACKEND_WEBUI_ROUTER = readFileSync(
  join(ROOT, '..', 'backend', 'app', 'gateway', 'routers', 'webui.py'),
  'utf8',
)
const BACKEND_WORKBENCH_AUTH = readFileSync(
  join(ROOT, '..', 'backend', 'packages', 'harness', 'evoflow', 'webui', 'workbench_auth.py'),
  'utf8',
)
const VERSION = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim()

describe('1.4.15 壳登录统一方案1：switch 主路径走工作台账密', () => {
  it('webui-remote 新增 loginWithWorkbench → POST /webui/login-workbench', () => {
    expect(WEBUI_REMOTE).toContain('export async function loginWithWorkbench')
    const fn = WEBUI_REMOTE.match(/export async function loginWithWorkbench[\s\S]*?\n}/)?.[0] ?? ''
    expect(fn).toContain("gatewayProxy('POST', '/webui/login-workbench'")
  })

  it('login.js switch 主路径调用 loginWithWorkbench；非 switch / local 旁路仍走 login()', () => {
    expect(LOGIN_PAGE).toContain('loginWithWorkbench,')
    expect(LOGIN_PAGE).toContain('const useWorkbench = switchMode && !localOpsMode')
    const submit = LOGIN_PAGE.match(/const useWorkbench[\s\S]*?await login\(\{ username, password \}\)/)?.[0] ?? ''
    expect(submit).toContain('await loginWithWorkbench({ username, password })')
    expect(submit).toContain('await login({ username, password })')
  })

  it('工作台登录后成功路径不回退：prepareAccountSwitch + saveAuthToken + reload', () => {
    const submit = LOGIN_PAGE.match(/const useWorkbench[\s\S]*?window\.location\.reload\(\)/)?.[0] ?? ''
    expect(submit).toContain('prepareAccountSwitch(resp.token)')
    expect(submit).toContain('saveAuthToken(resp.token)')
    expect(submit).toContain('window.location.reload()')
  })

  it('登录页文案指明 AI 工作台账密；不再宣称账号由「设置 → 用户权限」创建', () => {
    expect(LOGIN_PAGE).toContain('AI 工作台的账号与密码')
    expect(LOGIN_PAGE).toContain('workbench.kll666.cn')
    expect(LOGIN_PAGE).not.toContain('账号由「设置 → 用户权限」创建')
  })
})

describe('1.4.15 Local Admin / 远程 WebUI 旁路保留', () => {
  it('原 login() → POST /webui/login 仍在（旧壳本地户 evoflow_webui_users）', () => {
    const fn = WEBUI_REMOTE.match(/export async function login\([\s\S]*?\n}/)?.[0] ?? ''
    expect(fn).toContain("gatewayProxy('POST', '/webui/login'")
  })

  it('switch 页提供 ?local=1 次要入口「本机运维登录」，可切回工作台登录', () => {
    expect(LOGIN_PAGE).toContain('href="#/login?switch=1&local=1${redirectQ}"')
    expect(LOGIN_PAGE).toContain('本机运维登录')
    expect(LOGIN_PAGE).toContain('href="#/login?switch=1${redirectQ}"')
    expect(LOGIN_PAGE).toContain('使用 AI 工作台账号登录')
    // 切换模式互切保留 redirect 目标
    expect(LOGIN_PAGE).toContain("const redirectQ = redirect && redirect !== '/chat' ? `&redirect=${encodeURIComponent(redirect)}` : ''")
    // localOpsMode 仅在 switchMode 下生效，非 switch 远程页不受影响
    expect(LOGIN_PAGE).toContain("const localOpsMode = switchMode && params.get('local') === '1'")
  })

  it('会话隔离与 Local Admin 免登回程不回退', () => {
    expect(ACCOUNT_SESSION).toContain('export function prepareAccountSwitch')
    expect(ACCOUNT_SESSION).toContain('export function logoutToLocalAdmin')
    expect(ACCOUNT_SESSION).toContain('export function navigateSwitchUser')
    expect(SHELL_ACCOUNT).toContain('navigateSwitchUser')
  })
})

describe('1.4.15 文案与常量', () => {
  it('users.js 不再声称壳本地户是侧栏「切换用户」的主来源', () => {
    expect(USERS_SETTINGS).not.toContain('用于侧栏「切换用户」')
    expect(USERS_SETTINGS).not.toContain('切换用户 / 远程登录用')
    expect(USERS_SETTINGS).toContain('远程 WebUI 登录与本机运维旁路')
    expect(USERS_SETTINGS).toContain('AI 工作台账号')
  })

  it('shell-account 账户菜单提示日常切换用工作台账号；Local Admin 免登保留', () => {
    expect(SHELL_ACCOUNT).toContain('日常「切换用户」请用 AI 工作台账号')
    expect(SHELL_ACCOUNT).toContain('本机默认免登为本地管理员')
  })

  it('工作台常量仍钉线上域名（登录与 iframe 同源配置）', () => {
    expect(WORKBENCH_URLS).toContain("WORKBENCH_HOME_URL = 'https://workbench.kll666.cn/'")
  })

  it('VERSION = 1.4.16（1.4.16 回程离开首页刀 bump；登录统一业务测例不变）', () => {
    expect(VERSION).toBe('1.4.16')
  })
})

describe('1.4.15 后端对齐（跨读 backend 源码）', () => {
  it('Gateway 提供 POST /webui/login-workbench 代理路由（public 前缀自动覆盖）', () => {
    expect(BACKEND_WEBUI_ROUTER).toContain('"/login-workbench"')
    expect(BACKEND_WEBUI_ROUTER).toContain('ensure_workbench_principal')
    // 壳仍发自家 WebUI JWT；auth_method=workbench 标记来源
    expect(BACKEND_WEBUI_ROUTER).toContain('auth_method="workbench"')
  })

  it('principal 映射存在（workbench username → 壳 principal，无本地密码行）', () => {
    expect(readFileSync(join(ROOT, '..', 'backend', 'packages', 'harness', 'evoflow', 'authz', 'principals.py'), 'utf8'))
      .toContain('def ensure_workbench_principal(')
  })

  it('代理超时 ≤10s 且默认 base 钉工作台域名（env 可覆盖）', () => {
    expect(BACKEND_WORKBENCH_AUTH).toContain('WORKBENCH_LOGIN_TIMEOUT_S = 10.0')
    expect(BACKEND_WORKBENCH_AUTH).toContain('https://workbench.kll666.cn')
    expect(BACKEND_WORKBENCH_AUTH).toContain('EVOFLOW_WORKBENCH_AUTH_BASE')
    // 401 透传工作台中文文案
    expect(BACKEND_WORKBENCH_AUTH).toContain('用户名或密码不对')
  })
})

describe('1.4.15 禁区：无千川 / 生产写', () => {
  it('本刀触碰文件不含千川链路', () => {
    const forbidden = /千川|qianchuan|cj_?client|safe_deploy/
    for (const src of [LOGIN_PAGE, WEBUI_REMOTE, USERS_SETTINGS, SHELL_ACCOUNT, BACKEND_WORKBENCH_AUTH]) {
      expect(forbidden.test(src)).toBe(false)
    }
  })
})
