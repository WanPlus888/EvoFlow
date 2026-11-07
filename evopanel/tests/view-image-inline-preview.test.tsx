import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'

vi.mock('../src/lib/tauri-api.js', () => ({
  getGatewayBaseUrl: vi.fn(async () => 'http://127.0.0.1:8012'),
}))
vi.mock('../src/lib/webui-remote.js', () => ({
  getAuthToken: vi.fn(() => 'ui-token'),
}))
vi.mock('../src/lib/chat-lightbox.js', () => ({
  showChatLightbox: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Workbench inline image preview', () => {
  it('fetches a record-bound opaque ref into a revocable in-memory blob', async () => {
    const fetchSpy = vi.fn(async () => ({
      ok: true,
      status: 200,
      blob: async () => new Blob(['png-bytes'], { type: 'image/png' }),
    }))
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:workbench-preview')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.stubGlobal('fetch', fetchSpy)
    const { ViewImageInlinePreview } = await import('../src/react/components/ViewImageInlinePreview.js')
    const ref = 'workbench-image://rec_123/0/IMG-20261027-TRI-001'
    const view = render(<ViewImageInlinePreview imagePath={ref} alt="成品主图" />)

    await waitFor(() => expect(view.getByAltText('成品主图').getAttribute('src')).toBe('blob:workbench-preview'))
    const [requestedUrl, options] = fetchSpy.mock.calls[0]
    expect(requestedUrl).toBe('http://127.0.0.1:8012/api/opsboard/image-preview/rec_123/0')
    expect(options.headers.Authorization).toBe('Bearer ui-token')
    expect(options.headers['X-EvoFlow-External-Ref']).toBe('IMG-20261027-TRI-001')
    expect(requestedUrl).not.toContain('ticket=')
    expect(requestedUrl).not.toContain('IMG-20261027-TRI-001')

    view.unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:workbench-preview')
  })
})
