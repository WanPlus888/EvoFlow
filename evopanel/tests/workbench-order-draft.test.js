import { describe, expect, it } from 'vitest'
import {
  draftTypeLabel,
  isWorkbenchOrderDraftTool,
  parseWorkbenchOrderDraftOutput,
} from '../src/react/lib/workbench-order-draft.ts'

describe('workbench-order-draft', () => {
  it('detects tool name', () => {
    expect(isWorkbenchOrderDraftTool('draft_workbench_order')).toBe(true)
    expect(isWorkbenchOrderDraftTool('tool', 'draft_workbench_order')).toBe(true)
    expect(isWorkbenchOrderDraftTool('bash')).toBe(false)
  })

  it('parses JSON draft output', () => {
    const draft = parseWorkbenchOrderDraftOutput(
      JSON.stringify({
        status: 'draft',
        type: 'image',
        external_ref: 'EV-20261107-150000',
        product: '碎花连衣裙',
        qty: '8',
      }),
    )
    expect(draft?.external_ref).toBe('EV-20261107-150000')
    expect(draft?.type).toBe('image')
    expect(draftTypeLabel(draft?.type)).toBe('套图')
  })

  it('parses fenced or wrapped output', () => {
    const draft = parseWorkbenchOrderDraftOutput(
      '草稿如下：\n```json\n{"status":"draft","type":"video","external_ref":"EV-1"}\n```\n',
    )
    expect(draft?.external_ref).toBe('EV-1')
    expect(draftTypeLabel(draft?.type)).toBe('短视频')
  })

  it('returns null for unrelated output', () => {
    expect(parseWorkbenchOrderDraftOutput('hello')).toBeNull()
    expect(parseWorkbenchOrderDraftOutput({ ok: true })).toBeNull()
  })
})
