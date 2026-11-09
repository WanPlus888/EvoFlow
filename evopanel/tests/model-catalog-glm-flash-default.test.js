/**
 * 1.4.21 壳默认模型 GLM-5.3-Flash 刀测例（运营大脑侧）。
 * 运行：npx vitest run tests/model-catalog-glm-flash-default.test.js
 * 覆盖：官方名单/快捷目录含 Flash；默认回落优先 Flash 不停小米；
 * 会话钉死 mimo 不被改写；策略装配层源码事实钉（无 Key 处理）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import {
  defaultModelFromCatalog,
  resolveSessionModelName,
} from '../src/react/lib/model-catalog.js'
import { OFFICIAL_GLM_MODEL_IDS } from '../src/zcode-shared/official-glm-model-id.js'
import { MODEL_PRESETS } from '../src/lib/model-presets.js'

const ROOT = process.cwd()

function entry(name) {
  return { name, supportsVision: false, availabilityStatus: 'available' }
}

// 目录同时含小米与智谱 Flash 的最小夹具（模拟 1.4.21 投影后的 /api/models）。
const CATALOG_MIXED = [
  entry('mimo-v2.6-pro'),
  entry('mimo-v2.6-flash'),
  entry('glm-5.3-flash'),
  entry('glm-5.3'),
]

describe('1.4.21 官方名单与快捷目录露出 Flash', () => {
  it('官方 GLM 名单含 GLM-5.3-Flash（账号套餐规范 id）', () => {
    expect(OFFICIAL_GLM_MODEL_IDS).toContain('GLM-5.3-Flash')
    expect(OFFICIAL_GLM_MODEL_IDS).toContain('GLM-5.3')
  })

  it('面板智谱快捷目录含 glm-5.3-flash 且排在推荐区', () => {
    const zhipu = MODEL_PRESETS.zhipu || []
    const ids = zhipu.map((m) => m.id)
    expect(ids).toContain('glm-5.3-flash')
    expect(ids).toContain('glm-5.3')
    const flash = zhipu.find((m) => m.id === 'glm-5.3-flash')
    expect(flash.section).toBe('recommended')
  })
})

describe('1.4.21 默认回落优先 GLM-5.3-Flash', () => {
  it('primary 为小米默认且目录有 Flash → 选 Flash', () => {
    expect(defaultModelFromCatalog(CATALOG_MIXED, 'mimo-v2.6-pro')).toBe('glm-5.3-flash')
  })

  it('primary 缺失、目录首项为小米 → 选 Flash 而非 catalog[0]', () => {
    expect(defaultModelFromCatalog(CATALOG_MIXED, '')).toBe('glm-5.3-flash')
  })

  it('primary 已是 Flash / 其它正常模型 → 原样保留', () => {
    expect(defaultModelFromCatalog(CATALOG_MIXED, 'glm-5.3-flash')).toBe('glm-5.3-flash')
    expect(defaultModelFromCatalog(CATALOG_MIXED, 'glm-5.3')).toBe('glm-5.3')
  })

  it('目录无 Flash 时小米选择不被改写（不造目录）', () => {
    const xiaomiOnly = [entry('mimo-v2.6-pro'), entry('other-model')]
    expect(defaultModelFromCatalog(xiaomiOnly, 'mimo-v2.6-pro')).toBe('mimo-v2.6-pro')
    expect(defaultModelFromCatalog(xiaomiOnly, '')).toBe('mimo-v2.6-pro')
  })
})

describe('1.4.21 会话钉死守卫（§3.5）', () => {
  it('会话已钉死 mimo → 不被默认回落改写', () => {
    const picked = resolveSessionModelName(CATALOG_MIXED, {
      userPillModel: 'mimo-v2.6-pro',
      sessionContextModel: 'mimo-v2.6-pro',
      primaryModel: 'glm-5.3-flash',
      fromSessionSwitch: false,
    })
    expect(picked).toBe('mimo-v2.6-pro')
  })

  it('会话切换时 context 钉死 mimo → 仍保留 mimo', () => {
    const picked = resolveSessionModelName(CATALOG_MIXED, {
      sessionContextModel: 'mimo-v2.6-flash',
      primaryModel: 'glm-5.3-flash',
      fromSessionSwitch: true,
    })
    expect(picked).toBe('mimo-v2.6-flash')
  })
})

describe('1.4.21 zcode 默认策略装配层（源码事实钉）', () => {
  it('providerRuntime 策略：缺省/mimo-* 默认 → Flash；id 集合含两种拼法', () => {
    const src = readFileSync(
      join(ROOT, 'src/zcode-services/model-provider/providerRuntime.ts'),
      'utf8',
    )
    expect(src).toContain('GlmFlashDefaultSelectionPolicySource')
    expect(src).toContain('"glm-5.3-flash"')
    expect(src).toContain('"GLM-5.3-Flash"')
    // 小米判定为 mimo 前缀（覆盖 mimo-v2.6-pro / mimo-v2.6-flash 及后续版本）
    expect(src).toContain('startsWith("mimo")')
  })

  it('model-catalog.ts 不触碰凭证字段（Key 不回显守卫）', () => {
    const src = readFileSync(join(ROOT, 'src/react/lib/model-catalog.ts'), 'utf8')
    expect(/api_key|apiKey/i.test(src)).toBe(false)
  })
})
