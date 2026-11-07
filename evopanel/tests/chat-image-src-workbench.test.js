import { describe, expect, it } from 'vitest'
import { parseLegacyWorkbenchOutputRef, parseWorkbenchImageRef, resolveChatImageSrc } from '../src/lib/chat-image-src.js'

describe('workbench image references', () => {
  it('parses opaque workbench record references without converting them to local paths', () => {
    expect(parseWorkbenchImageRef('workbench-image://rec_123/0/IMG-20261027-KNIT-TRI-001')).toEqual({
      recordId: 'rec_123', itemIndex: 0, externalRef: 'IMG-20261027-KNIT-TRI-001',
    })
    expect(resolveChatImageSrc('workbench-image://rec_123/0/IMG-20261027-KNIT-TRI-001')).toBe('')
  })

  it('parses legacy absolute Workbench output paths without exposing an EvoFlow path', () => {
    const legacy = '/home/ubuntu/workbench/data/outputs/rec_123/成品/00_主图.png'
    expect(parseLegacyWorkbenchOutputRef(legacy)).toEqual({
      recordId: 'rec_123', itemIndex: 0, externalRef: '',
    })
    expect(resolveChatImageSrc(legacy)).toBe('')
  })

  it('rejects malformed or cross-record reference strings', () => {
    expect(parseWorkbenchImageRef('workbench-image://rec_123/0')).toBeNull()
    expect(parseWorkbenchImageRef('workbench-image://rec_123/../IMG-1')).toBeNull()
    expect(parseWorkbenchImageRef('workbench-image://rec_123/0/IMG-1?ticket=secret')).toBeNull()
  })
})
