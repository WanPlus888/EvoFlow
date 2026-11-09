/**
 * 1.4.18 工作台 SSO 垫片（src-tauri/src/workbench_sso_shim.js）沙箱回归：
 * - 守卫：top 窗 / 错 origin / 错父源 / 嵌套 iframe / 已有 pywebview → 一律不注入
 * - sso_save：password 即收即弃，发出的消息不含 password（AC7）
 * - wb_token setItem/removeItem 触发 identity（去重），其他 key 不触发
 * - sso_login：请求带 nonce、只认父源应答；3s 超时 {ok:false}
 * - 冷启：无 token → 向父窗要 → 种 token + cookie + reload 只一次（防循环）
 * 用 node:vm 隔离跑 IIFE 源码（vitest happy-dom 环境下 node 内建可用）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import vm from 'node:vm'

const SHIM = readFileSync(join(process.cwd(), 'src-tauri', 'src', 'workbench_sso_shim.js'), 'utf8')
const WB = 'https://workbench.kll666.cn'
const PARENT_ORIGIN = 'tauri://localhost'

/** ES5-fake Storage：原型方法可被垫片包装。 */
function makeStorageClass() {
  function StorageProto() {}
  StorageProto.prototype.setItem = function (k, v) {
    this._d[k] = String(v)
  }
  StorageProto.prototype.removeItem = function (k) {
    delete this._d[k]
  }
  StorageProto.prototype.getItem = function (k) {
    return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null
  }
  return StorageProto
}

/**
 * @param {{origin?: string, ancestor?: string[], isTop?: boolean, nested?: boolean, hasPywebview?: boolean, readyState?: string}} [opts]
 */
function makeSandbox(opts = {}) {
  const {
    origin = WB,
    ancestor = [PARENT_ORIGIN],
    isTop = false,
    nested = false,
    hasPywebview = false,
    readyState = 'complete',
  } = opts

  const StorageProto = makeStorageClass()
  const origSetItem = StorageProto.prototype.setItem
  const origRemoveItem = StorageProto.prototype.removeItem
  const localStorage = Object.create(StorageProto.prototype)
  localStorage._d = {}
  const sessionStorage = Object.create(StorageProto.prototype)
  sessionStorage._d = {}

  const parentMessages = []
  const iframeListeners = []
  const timers = []
  const reloads = []
  const cookies = []
  const domReadyFns = []

  const parentWin = {
    origin: PARENT_ORIGIN,
    postMessage: (msg, targetOrigin) => {
      parentMessages.push({ msg, targetOrigin })
    },
  }
  const topWin = nested ? { origin: 'https://elsewhere.example' } : parentWin

  const iframeWindow = {
    addEventListener: (t, fn) => {
      iframeListeners.push({ t, fn })
    },
    removeEventListener: (t, fn) => {
      const i = iframeListeners.findIndex((l) => l.t === t && l.fn === fn)
      if (i >= 0) iframeListeners.splice(i, 1)
    },
  }
  iframeWindow.localStorage = localStorage
  iframeWindow.sessionStorage = sessionStorage
  if (hasPywebview) iframeWindow.pywebview = { api: { sso_login: () => {}, sso_save: () => {} } }

  const sandbox = {
    window: iframeWindow,
    location: {
      origin,
      ancestorOrigins: ancestor,
      reload: () => {
        reloads.push(Date.now())
      },
    },
    document: {
      readyState,
      addEventListener: (t, fn) => {
        domReadyFns.push(fn)
      },
    },
    Storage: StorageProto,
    localStorage,
    sessionStorage,
    setTimeout: (fn) => {
      timers.push(fn)
      return timers.length
    },
    clearTimeout: () => {},
    Promise,
    Date,
    Math,
    console,
  }
  // document.cookie 赋值捕获
  Object.defineProperty(sandbox.document, 'cookie', {
    get: () => (cookies.length ? cookies[cookies.length - 1] : ''),
    set: (v) => {
      cookies.push(String(v))
    },
    configurable: true,
  })
  iframeWindow.top = isTop ? iframeWindow : topWin
  iframeWindow.parent = parentWin

  const context = vm.createContext(sandbox)
  return {
    context,
    sandbox,
    Storage: StorageProto,
    parentMessages,
    iframeListeners,
    timers,
    reloads,
    cookies,
    domReadyFns,
    parentWin,
    iframeWindow,
    localStorage,
    sessionStorage,
    origSetItem,
    origRemoveItem,
    run: () => vm.runInContext(SHIM, context, { filename: 'workbench_sso_shim.js' }),
    /** 模拟父窗按约定回 sso-reply。 */
    replySso: (nonce, token) => {
      for (const { fn } of iframeListeners) {
        fn({ source: parentWin, origin: PARENT_ORIGIN, data: { type: 'evoflow-wb-sso-reply', nonce, token } })
      }
    },
    /** 模拟 sso-reply 超时回调触发。 */
    fireTimers: () => {
      const pending = timers.splice(0)
      for (const fn of pending) fn()
    },
  }
}

const flushMicrotasks = () => new Promise((r) => setImmediate(r))

/** 只取 identity 类消息（boot 期还会发 sso-request）。 */
const identityMsgs = (s) => s.parentMessages.filter((m) => m.msg && m.msg.type === 'evoflow-wb-identity')

describe('1.4.18 垫片守卫（不满足即零注入）', () => {
  it('top 窗（非 iframe）不注入', () => {
    const s = makeSandbox({ isTop: true })
    s.run()
    expect(s.iframeWindow.pywebview).toBeUndefined()
    expect(s.Storage.prototype.setItem).toBe(s.origSetItem)
  })

  it('非工作台 origin 不注入', () => {
    const s = makeSandbox({ origin: 'https://example.com' })
    s.run()
    expect(s.iframeWindow.pywebview).toBeUndefined()
    expect(s.Storage.prototype.setItem).toBe(s.origSetItem)
  })

  it('父源不在壳白名单（外部网站嵌工作台）不注入', () => {
    const s = makeSandbox({ ancestor: ['https://evil.example'] })
    s.run()
    expect(s.iframeWindow.pywebview).toBeUndefined()
    expect(s.Storage.prototype.setItem).toBe(s.origSetItem)
    expect(s.parentMessages).toHaveLength(0)
  })

  it('嵌套 iframe（parent !== top）不注入', () => {
    const s = makeSandbox({ nested: true })
    s.run()
    expect(s.iframeWindow.pywebview).toBeUndefined()
  })

  it('已有真 pywebview（托盘）不覆盖', () => {
    const s = makeSandbox({ hasPywebview: true })
    s.run()
    expect(s.iframeWindow.pywebview.api.sso_login).not.toBeNull()
    expect(s.parentMessages).toHaveLength(0) // 没有任何消息发出
  })

  it('白名单内的 dev 父源可注入（127.0.0.1:1521）', async () => {
    const s = makeSandbox({ ancestor: ['http://127.0.0.1:1521'] })
    s.localStorage.setItem('wb_token', 'tok-dev')
    s.run()
    await flushMicrotasks()
    expect(s.iframeWindow.pywebview).toBeDefined()
    expect(s.parentMessages.length).toBeGreaterThan(0)
  })
})

describe('1.4.18 sso_save / wb_token 观察（工作台 → 壳）', () => {
  it('sso_save 转发 token，password 不出现在任何消息里（AC7）', async () => {
    const s = makeSandbox()
    s.run()
    await flushMicrotasks() // boot：无 token → sso_login 超时路径挂起（不触发）
    s.iframeWindow.pywebview.api.sso_save(WB, 'jennifer', 'wb-tok-1', 'plaintext-password-9')
    await flushMicrotasks()
    const identities = identityMsgs(s)
    expect(identities).toHaveLength(1)
    const { msg, targetOrigin } = identities[0]
    expect(targetOrigin).toBe(PARENT_ORIGIN)
    expect(msg.type).toBe('evoflow-wb-identity')
    expect(msg.token).toBe('wb-tok-1')
    expect(msg.reason).toBe('login')
    expect(JSON.stringify(s.parentMessages)).not.toContain('plaintext-password-9')
  })

  it("setItem('wb_token') 触发 identity；其他 key 不触发", async () => {
    const s = makeSandbox()
    s.run()
    await flushMicrotasks()
    s.fireTimers() // 掐掉 sso_login 3s 超时挂起
    s.localStorage.setItem('other_key', 'v')
    expect(identityMsgs(s)).toHaveLength(0)
    s.localStorage.setItem('wb_token', 'tok-1')
    expect(identityMsgs(s)).toHaveLength(1)
    expect(identityMsgs(s)[0].msg).toMatchObject({ type: 'evoflow-wb-identity', token: 'tok-1', reason: 'change' })
    // 同值去重
    s.localStorage.setItem('wb_token', 'tok-1')
    expect(identityMsgs(s)).toHaveLength(1)
    // removeItem → identity null
    s.localStorage.removeItem('wb_token')
    expect(identityMsgs(s)).toHaveLength(2)
    expect(identityMsgs(s)[1].msg).toMatchObject({ type: 'evoflow-wb-identity', token: null, reason: 'change' })
  })

  it('已登录老用户冷启 → boot identity（AC1）', async () => {
    const s = makeSandbox()
    s.localStorage.setItem('wb_token', 'boot-tok')
    s.run()
    await flushMicrotasks()
    expect(identityMsgs(s)).toHaveLength(1)
    expect(identityMsgs(s)[0].msg).toMatchObject({ type: 'evoflow-wb-identity', token: 'boot-tok', reason: 'boot' })
    expect(s.reloads).toHaveLength(0)
  })
})

describe('1.4.18 sso_login（壳 → 工作台）', () => {
  it('发 sso-request（带 nonce、targetOrigin=父源），父窗回 token → {ok:true,token}', async () => {
    const s = makeSandbox()
    s.run()
    await flushMicrotasks() // boot 已发过一条 sso-request
    const req = s.parentMessages.find((m) => m.msg.type === 'evoflow-wb-sso-request')
    expect(req).toBeTruthy()
    expect(req.targetOrigin).toBe(PARENT_ORIGIN)
    expect(typeof req.msg.nonce).toBe('string')
    const p = s.iframeWindow.pywebview.api.sso_login()
    let settled = null
    p.then((r) => {
      settled = r
    })
    const req2 = s.parentMessages.at(-1)
    s.replySso(req2.msg.nonce, 'tok-from-shell')
    await flushMicrotasks()
    expect(settled).toEqual({ ok: true, token: 'tok-from-shell' })
  })

  it('3s 超时 → {ok:false}，不种 token 不 reload', async () => {
    const s = makeSandbox()
    s.run()
    await flushMicrotasks()
    const p = s.iframeWindow.pywebview.api.sso_login()
    let settled = null
    p.then((r) => {
      settled = r
    })
    s.fireTimers() // 触发 3s 超时回调
    await flushMicrotasks()
    expect(settled).toEqual({ ok: false })
    expect(s.reloads).toHaveLength(0)
    expect(s.localStorage.getItem('wb_token')).toBeNull()
  })
})

describe('1.4.18 冷启种 token（AC3 壳先登录）', () => {
  it('无 token → 向父窗要 → 种 localStorage + cookie + reload 只一次', async () => {
    const s = makeSandbox()
    s.run()
    await flushMicrotasks() // boot 发出 sso-request
    const req = s.parentMessages.find((m) => m.msg.type === 'evoflow-wb-sso-request')
    s.replySso(req.msg.nonce, 'seed-tok')
    await flushMicrotasks()
    expect(s.localStorage.getItem('wb_token')).toBe('seed-tok')
    expect(s.sessionStorage.getItem('ef-wb-sso-seeded')).toBe('1')
    expect(s.cookies[0]).toContain('wb_token=seed-tok')
    expect(s.cookies[0]).toContain('path=/')
    expect(s.cookies[0]).toContain('SameSite=Lax')
    expect(s.cookies[0]).toContain('max-age=2592000')
    expect(s.reloads).toHaveLength(1)
    // 二次执行（reload 后同一会话）：token 已在 → 不再种、不再 reload（防循环）
    s.run()
    await flushMicrotasks()
    expect(s.reloads).toHaveLength(1)
    expect(s.sessionStorage.getItem('ef-wb-sso-seeded')).toBe('1')
  })

  it('父窗没有 token（回 null）→ 不种、不 reload', async () => {
    const s = makeSandbox()
    s.run()
    await flushMicrotasks()
    const req = s.parentMessages.find((m) => m.msg.type === 'evoflow-wb-sso-request')
    s.replySso(req.msg.nonce, null)
    await flushMicrotasks()
    expect(s.localStorage.getItem('wb_token')).toBeNull()
    expect(s.reloads).toHaveLength(0)
  })
})
