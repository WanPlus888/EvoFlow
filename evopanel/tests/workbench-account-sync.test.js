/**
 * 1.4.18 工作台账号同步器（lib/workbench-account-sync.js）行为回归：
 * - 来源校验（AC8）：非工作台 origin / 非 iframe source 一律忽略
 * - 换号主链路：login-workbench-token → 同账号 no-op / 不同账号静默切号
 * - token=null 不清壳（P0）；local-ops-pin 本会话旁路（AC5）
 * - 404/405 只 toast 一次（AC6）；401/5xx 静默、下次事件再试
 * - /workbench-home 不 reload（防 iframe 循环）；其他路由同号只 reload 一次
 * - sso-request 应答 targetOrigin 钉死工作台源（AC3/AC8）
 * 环境用仓库标准 happy-dom（vitest.config include 列表登记本文件）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../src/lib/webui-remote.js', () => ({
  loginWithWorkbenchToken: vi.fn(),
  saveAuthToken: vi.fn(),
}))
vi.mock('../src/lib/account-session.js', () => ({
  ensureMeReady: vi.fn(),
  prepareAccountSwitch: vi.fn(),
  refreshMe: vi.fn(),
}))
vi.mock('../src/components/toast.js', () => ({ toast: vi.fn() }))

import { loginWithWorkbenchToken, saveAuthToken } from '../src/lib/webui-remote.js'
import { ensureMeReady, prepareAccountSwitch, refreshMe } from '../src/lib/account-session.js'
import { toast } from '../src/components/toast.js'
import { __resetForTest, initWorkbenchAccountSync } from '../src/lib/workbench-account-sync.js'

const WB = 'https://workbench.kll666.cn'
const api = loginWithWorkbenchToken
const meApi = ensureMeReady
const prep = prepareAccountSwitch
const refresh = refreshMe
const toastFn = toast

/** 等 500ms 防抖 + 微任务队列排空。 */
const tick = () => new Promise((r) => setTimeout(r, 620))

/** 挂一个 iframe 并以它的 contentWindow 为 source 派发 message。 */
function fireFromIframe(origin, data, source) {
  const frame = document.createElement('iframe')
  document.body.appendChild(frame)
  const ev = new MessageEvent('message', { data, origin })
  const src = source || frame.contentWindow
  try {
    Object.defineProperty(ev, 'source', { value: src })
  } catch {
    /* happy-dom 若已带 source 则无需覆盖 */
  }
  window.dispatchEvent(ev)
  return frame
}

let reloadSpy

beforeEach(() => {
  __resetForTest()
  api.mockReset()
  meApi.mockReset()
  prep.mockReset()
  refresh.mockReset()
  saveAuthToken.mockReset()
  toastFn.mockReset()
  try {
    sessionStorage.clear()
  } catch { /* ignore */ }
  try {
    window.localStorage?.clear?.()
  } catch { /* ignore */ }
  document.querySelectorAll('iframe').forEach((f) => f.remove())
  window.location.hash = '#/chat'
  reloadSpy = vi.spyOn(window.location, 'reload').mockImplementation(() => {})
})

afterEach(() => {
  reloadSpy?.mockRestore()
  __resetForTest()
})

describe('1.4.18 来源校验（AC8）', () => {
  it('非工作台 origin 的消息全部忽略', async () => {
    initWorkbenchAccountSync()
    fireFromIframe('https://evil.example.com', { type: 'evoflow-wb-identity', token: 'tok-a', reason: 'login' })
    await tick()
    expect(api).not.toHaveBeenCalled()
  })

  it('source 不是页面内 iframe 的 contentWindow 时忽略', async () => {
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'tok-a', reason: 'login' }, window)
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'tok-a', reason: 'login' }, { fake: 'window' })
    await tick()
    expect(api).not.toHaveBeenCalled()
  })

  it('未知消息类型 / 非对象 payload 忽略', async () => {
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'someone-elses-message', token: 'tok-a' })
    fireFromIframe(WB, 'not-an-object')
    await tick()
    expect(api).not.toHaveBeenCalled()
  })
})

describe('1.4.18 换号主链路', () => {
  it('Local Admin 会话收到工作台 token → 静默切号（AC1）', async () => {
    meApi.mockResolvedValue({ authSource: 'local', username: null, principalId: 'local-admin' })
    api.mockResolvedValue({ token: 'shell-jwt-1', username: 'jennifer' })
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'boot' })
    await tick()
    expect(api).toHaveBeenCalledWith({ workbench_token: 'wb-tok-1' })
    expect(prep).toHaveBeenCalledWith('shell-jwt-1')
    expect(saveAuthToken).toHaveBeenCalledWith('shell-jwt-1')
    expect(refresh).toHaveBeenCalledWith({ retries: 2 })
    expect(sessionStorage.getItem('evoflow_wb_sso_token')).toBe('wb-tok-1')
    expect(toastFn).toHaveBeenCalledWith('已同步为工作台账号 @jennifer', 'success', expect.anything())
  })

  it('已是同一工作台账号（JWT）→ no-op：不清缓存、不刷新（AC4）', async () => {
    meApi.mockResolvedValue({ authSource: 'jwt', username: 'jennifer' })
    api.mockResolvedValue({ token: 'shell-jwt-1', username: 'jennifer' })
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'change' })
    await tick()
    expect(api).toHaveBeenCalledTimes(1)
    expect(prep).not.toHaveBeenCalled()
    expect(saveAuthToken).not.toHaveBeenCalled()
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it('不同账号（jwt bob → jennifer）→ 切号', async () => {
    meApi.mockResolvedValue({ authSource: 'jwt', username: 'bob' })
    api.mockResolvedValue({ token: 'shell-jwt-2', username: 'jennifer' })
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-2', reason: 'change' })
    await tick()
    expect(prep).toHaveBeenCalledWith('shell-jwt-2')
    expect(refresh).toHaveBeenCalled()
  })

  it('同 token 重复事件只打一次网关（去重，AC4）', async () => {
    meApi.mockResolvedValue({ authSource: 'jwt', username: 'jennifer' })
    api.mockResolvedValue({ token: 'shell-jwt-1', username: 'jennifer' })
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'boot' })
    await tick()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'change' })
    await tick()
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('token=null（工作台退出）→ 什么都不做（P0 不清壳）', async () => {
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: null, reason: 'change' })
    fireFromIframe(WB, { type: 'evoflow-wb-identity', reason: 'change' })
    await tick()
    expect(api).not.toHaveBeenCalled()
    expect(prep).not.toHaveBeenCalled()
  })

  it('本机运维 pin（?local=1 登录后）本会话跳过自动同步（AC5）', async () => {
    sessionStorage.setItem('ef-local-ops-pin', '1')
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'login' })
    await tick()
    expect(api).not.toHaveBeenCalled()
  })
})

describe('1.4.18 网关未升级 / 失败路径', () => {
  it('404 → console.warn + 只 toast 一次「网关未升级」（AC6）', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    api.mockRejectedValue(Object.assign(new Error('Not Found'), { status: 404 }))
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'boot' })
    await tick()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'change' })
    await tick()
    expect(api).toHaveBeenCalledTimes(2) // 每次事件都仍会尝试（无去重副作用）
    expect(toastFn).toHaveBeenCalledTimes(1)
    expect(toastFn).toHaveBeenCalledWith('网关未升级，账号暂不能自动同步', 'warning', expect.anything())
    expect(sessionStorage.getItem('ef-wb-sync-gw-not-upgraded')).toBe('1')
    expect(reloadSpy).not.toHaveBeenCalled()
    warn.mockRestore()
  })

  it('401（工作台 token 失效）→ 静默，不 toast 不 reload', async () => {
    api.mockRejectedValue(Object.assign(new Error('Unauthorized'), { status: 401 }))
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'boot' })
    await tick()
    expect(toastFn).not.toHaveBeenCalled()
    expect(reloadSpy).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('evoflow_wb_sso_token')).toBeNull()
  })

  it('5xx 静默，且不记去重——下次事件再试成功可切号', async () => {
    meApi.mockResolvedValue({ authSource: 'local', username: null })
    api.mockRejectedValueOnce(Object.assign(new Error('boom'), { status: 502 }))
    api.mockResolvedValue({ token: 'shell-jwt-1', username: 'jennifer' })
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'boot' })
    await tick()
    expect(prep).not.toHaveBeenCalled() // 失败未切
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'change' })
    await tick()
    expect(api).toHaveBeenCalledTimes(2)
    expect(prep).toHaveBeenCalledWith('shell-jwt-1') // 重试成功
  })
})

describe('1.4.18 reload 策略', () => {
  it('当前路由是 /workbench-home 时不 reload（防 iframe 重载循环）', async () => {
    window.location.hash = '#/workbench-home'
    meApi.mockResolvedValue({ authSource: 'local', username: null })
    api.mockResolvedValue({ token: 'shell-jwt-1', username: 'jennifer' })
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'boot' })
    await tick()
    expect(prep).toHaveBeenCalled()
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it('其他路由切号 reload，且同一 username 只 reload 一次', async () => {
    meApi.mockResolvedValue({ authSource: 'local', username: null })
    api.mockResolvedValue({ token: 'shell-jwt-1', username: 'jennifer' })
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'boot' })
    await tick()
    expect(reloadSpy).toHaveBeenCalledTimes(1)
    // 换号事件再来（不同 token、同目标账号）→ 不再 reload
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-9', reason: 'change' })
    await tick()
    expect(reloadSpy).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('ef-wb-sync-reload')).toBe('jennifer')
  })
})

describe('1.4.18 sso-request 应答（壳 → 工作台，AC3）', () => {
  it('回发 token 且 targetOrigin 钉死工作台源', async () => {
    sessionStorage.setItem('evoflow_wb_sso_token', 'wb-seed-tok')
    initWorkbenchAccountSync()
    const frame = fireFromIframe(WB, { type: 'evoflow-wb-sso-request', nonce: 'n-1' })
    const post = vi.spyOn(frame.contentWindow, 'postMessage')
    // 重新派发一次拿到 spy（spy 需在事件前挂上）
    const ev = new MessageEvent('message', { data: { type: 'evoflow-wb-sso-request', nonce: 'n-2' }, origin: WB })
    try {
      Object.defineProperty(ev, 'source', { value: frame.contentWindow })
    } catch { /* ignore */ }
    window.dispatchEvent(ev)
    expect(post).toHaveBeenCalledWith(
      { type: 'evoflow-wb-sso-reply', nonce: 'n-2', token: 'wb-seed-tok' },
      WB,
    )
  })

  it('无种子 token 时回 null（工作台自己弹登录，不伪造免登）', async () => {
    initWorkbenchAccountSync()
    const frame = fireFromIframe(WB, { type: 'evoflow-wb-sso-request', nonce: 'n-3' })
    const post = vi.spyOn(frame.contentWindow, 'postMessage')
    const ev = new MessageEvent('message', { data: { type: 'evoflow-wb-sso-request', nonce: 'n-4' }, origin: WB })
    try {
      Object.defineProperty(ev, 'source', { value: frame.contentWindow })
    } catch { /* ignore */ }
    window.dispatchEvent(ev)
    expect(post).toHaveBeenCalledWith(
      { type: 'evoflow-wb-sso-reply', nonce: 'n-4', token: null },
      WB,
    )
  })
})

describe('1.4.18 初始化幂等', () => {
  it('initWorkbenchAccountSync 重复调用只挂一个监听', async () => {
    meApi.mockResolvedValue({ authSource: 'local', username: null })
    api.mockResolvedValue({ token: 'shell-jwt-1', username: 'jennifer' })
    initWorkbenchAccountSync()
    initWorkbenchAccountSync()
    fireFromIframe(WB, { type: 'evoflow-wb-identity', token: 'wb-tok-1', reason: 'boot' })
    await tick()
    expect(api).toHaveBeenCalledTimes(1)
  })
})
