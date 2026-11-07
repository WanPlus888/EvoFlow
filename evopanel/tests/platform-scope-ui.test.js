// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import {
  bindPlatformScopePanel,
  inferTriStateMode,
  mapPlatformDomains,
  platformScopeAllowedCount,
  platformScopeSummaryText,
  readPlatformScopeFromEditor,
  renderPlatformScopePanel,
  resolveTriStatePayload,
  setPlatformScopeState,
} from '../src/lib/platform-scope-ui.js'

const DOMAINS = mapPlatformDomains([
  {
    domain: 'knowledge',
    title: '知识库',
    risk_counts: { read: 6, write: 4, destructive: 2 },
    actions: [
      { name: 'knowledge.list', summary: '列出知识库', risk: 'read' },
      { name: 'knowledge.create', summary: '新建知识库', risk: 'write' },
      { name: 'knowledge.delete', summary: '删除知识库', risk: 'destructive' },
    ],
  },
  {
    domain: 'media',
    title: '媒体',
    risk_counts: { read: 1, write: 2 },
    actions: [
      { name: 'media.catalog', summary: '媒体目录', risk: 'read' },
      { name: 'media.generate_image', summary: '生图', risk: 'write' },
      { name: 'media.generate_video', summary: '生视频', risk: 'write' },
    ],
  },
])

function selectMode(overlay, value) {
  overlay.querySelectorAll('input[name=platform_mode]').forEach((r) => {
    r.checked = r.value === value
  })
  const checked = overlay.querySelector(`input[name=platform_mode][value=${value}]`)
  checked?.dispatchEvent(new Event('change'))
}

function mountEditor({ scope = null, platformChecked = false } = {}) {
  const overlay = document.createElement('div')
  overlay.innerHTML = `
    <div class="editor-tool-list">
      <input type="checkbox" name="tools" value="platform" ${platformChecked ? 'checked' : ''}>
    </div>
    ${renderPlatformScopePanel(DOMAINS, scope)}
  `
  document.body.appendChild(overlay)
  bindPlatformScopePanel(overlay, DOMAINS)
  return overlay
}

describe('renderPlatformScopePanel', () => {
  it('renders hidden panel with domain rows; visible only when platform checked', () => {
    const overlay = mountEditor({ platformChecked: false })
    const panel = overlay.querySelector('[data-platform-scope]')
    expect(panel).toBeTruthy()
    expect(panel.hidden).toBe(true)
    expect(overlay.querySelectorAll('.re-ps-domain').length).toBe(2)
  })

  it('shows panel when platform checkbox is checked', () => {
    const overlay = mountEditor({ platformChecked: true })
    expect(overlay.querySelector('[data-platform-scope]').hidden).toBe(false)
  })

  it('pre-checks saved custom scope (domain + max_risk)', () => {
    const scope = { mode: 'custom', domains: ['knowledge'], actions: [], max_risk: 'read' }
    const overlay = mountEditor({ scope, platformChecked: true })
    expect(overlay.querySelector('input[name=platform_mode][value=custom]').checked).toBe(true)
    expect(overlay.querySelector('input[name=platform_max_risk][value=read]').checked).toBe(true)
    const domCb = overlay.querySelector('input[name=platform_domains][value="knowledge"]')
    expect(domCb.checked).toBe(true)
    const actionCbs = [...overlay.querySelectorAll('.re-ps-domain[data-domain=knowledge] input[name=platform_actions]')]
    expect(actionCbs.every((cb) => cb.checked)).toBe(true)
  })

  it('renders four modes including none and all', () => {
    const overlay = mountEditor({ platformChecked: true })
    const values = [...overlay.querySelectorAll('input[name=platform_mode]')].map((r) => r.value)
    expect(values).toEqual(['unrestricted', 'all', 'none', 'custom'])
  })
})

describe('readPlatformScopeFromEditor', () => {
  it('returns null when mode = unrestricted (legacy 不设限)', () => {
    const overlay = mountEditor({ platformChecked: true })
    expect(overlay.querySelector('input[name=platform_mode][value=unrestricted]').checked).toBe(true)
    expect(readPlatformScopeFromEditor(overlay)).toBeNull()
  })

  it('returns null when panel hidden (platform unchecked)', () => {
    const overlay = mountEditor({ platformChecked: false })
    expect(readPlatformScopeFromEditor(overlay)).toBeNull()
  })

  it('returns mode=all with max_risk', () => {
    const overlay = mountEditor({ platformChecked: true })
    selectMode(overlay, 'all')
    overlay.querySelector('input[name=platform_max_risk][value=read]').checked = true
    expect(readPlatformScopeFromEditor(overlay)).toEqual({
      mode: 'all',
      domains: [],
      actions: [],
      max_risk: 'read',
    })
  })

  it('returns mode=none', () => {
    const overlay = mountEditor({ platformChecked: true })
    selectMode(overlay, 'none')
    expect(readPlatformScopeFromEditor(overlay)).toEqual({
      mode: 'none',
      domains: [],
      actions: [],
      max_risk: 'write',
    })
  })

  it('domain checked + one action unchecked → minus-prefixed deny entry', () => {
    const overlay = mountEditor({ platformChecked: true })
    selectMode(overlay, 'custom')
    const domCb = overlay.querySelector('input[name=platform_domains][value="knowledge"]')
    domCb.checked = true
    domCb.dispatchEvent(new Event('change'))
    const del = overlay.querySelector('input[name=platform_actions][value="knowledge.delete"]')
    del.checked = false
    del.dispatchEvent(new Event('change'))
    const scope = readPlatformScopeFromEditor(overlay)
    expect(scope).toEqual({
      mode: 'custom',
      domains: ['knowledge'],
      actions: ['-knowledge.delete'],
      max_risk: 'write',
    })
  })

  it('domain unchecked + single action checked → bare action grant', () => {
    const overlay = mountEditor({ platformChecked: true })
    selectMode(overlay, 'custom')
    const cb = overlay.querySelector('input[name=platform_actions][value="media.catalog"]')
    cb.checked = true
    cb.dispatchEvent(new Event('change'))
    const scope = readPlatformScopeFromEditor(overlay)
    expect(scope.domains).toEqual([])
    expect(scope.actions).toEqual(['media.catalog'])
  })
})

describe('summary counting', () => {
  it('counts all for null scope', () => {
    expect(platformScopeAllowedCount(DOMAINS, null)).toEqual({ domains: 2, actions: 6 })
    expect(platformScopeSummaryText(DOMAINS, null)).toContain('不设限')
  })

  it('summarizes none and all', () => {
    expect(platformScopeSummaryText(DOMAINS, { mode: 'none' })).toBe('全部禁用')
    expect(platformScopeSummaryText(DOMAINS, { mode: 'all', max_risk: 'read' })).toBe('全量（上限 只读）')
  })

  it('counts domain grants minus denies plus bare allows', () => {
    const scope = { mode: 'custom', domains: ['knowledge'], actions: ['-knowledge.delete', 'media.catalog'], max_risk: 'write' }
    expect(platformScopeAllowedCount(DOMAINS, scope)).toEqual({ domains: 1, actions: 3 })
    expect(platformScopeSummaryText(DOMAINS, scope)).toBe('1 域 / 3 动作（上限 可写）')
  })
})

describe('tools/MCP tri-state', () => {
  it('infers inherit / none / custom from stored value', () => {
    expect(inferTriStateMode(null)).toBe('inherit')
    expect(inferTriStateMode(undefined)).toBe('inherit')
    expect(inferTriStateMode([])).toBe('none')
    expect(inferTriStateMode(['bash', 'platform'])).toBe('custom')
  })

  it('resolves payload for each mode', () => {
    expect(resolveTriStatePayload('inherit', ['bash'])).toBeNull()
    expect(resolveTriStatePayload('none', ['bash'])).toEqual([])
    expect(resolveTriStatePayload('custom', ['bash', 'platform'])).toEqual(['bash', 'platform'])
  })
})

describe('setPlatformScopeState', () => {
  it('programmatically applies custom scope for templates', () => {
    const overlay = mountEditor({ platformChecked: true, scope: null })
    setPlatformScopeState(overlay, {
      mode: 'custom',
      domains: ['media'],
      actions: [],
      max_risk: 'write',
    })
    expect(overlay.querySelector('input[name=platform_mode][value=custom]').checked).toBe(true)
    expect(overlay.querySelector('input[name=platform_domains][value="media"]').checked).toBe(true)
    expect(overlay.querySelector('input[name=platform_max_risk][value=write]').checked).toBe(true)
    const scope = readPlatformScopeFromEditor(overlay)
    expect(scope.mode).toBe('custom')
    expect(scope.domains).toEqual(['media'])
  })

  it('programmatically applies all + none without collapsing to unrestricted', () => {
    const overlay = mountEditor({ platformChecked: true, scope: null })
    setPlatformScopeState(overlay, { mode: 'all', domains: [], actions: [], max_risk: 'read' })
    expect(overlay.querySelector('input[name=platform_mode][value=all]').checked).toBe(true)
    expect(readPlatformScopeFromEditor(overlay)).toEqual({
      mode: 'all',
      domains: [],
      actions: [],
      max_risk: 'read',
    })
    setPlatformScopeState(overlay, { mode: 'none', domains: [], actions: [], max_risk: 'write' })
    expect(overlay.querySelector('input[name=platform_mode][value=none]').checked).toBe(true)
    expect(readPlatformScopeFromEditor(overlay).mode).toBe('none')
  })
})
