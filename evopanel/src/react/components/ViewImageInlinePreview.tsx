import { memo, useEffect, useState, type SyntheticEvent } from 'react'
import { showChatLightbox } from '../../lib/chat-lightbox.js'
import { resolveMediaAssetSrc } from '../../lib/chat-normalize.js'
import { parseLegacyWorkbenchOutputRef, parseWorkbenchImageRef } from '../../lib/chat-image-src.js'
import { getGatewayBaseUrl } from '../../lib/tauri-api.js'
import { getAuthToken } from '../../lib/webui-remote.js'

type Props = {
  imagePath: string
  /** 可选：视觉分析结果摘要，挂在图下方 */
  caption?: string
  alt?: string
}

/**
 * view_image 工具结果：把图片挂在工具卡下方（对齐 media_image_generate / 浏览器截图）。
 * 点击仍走 lightbox；完整分析文本继续由 ViewImageDetailModal 承接。
 */
function ViewImageInlinePreviewInner({ imagePath, caption, alt }: Props) {
  const [broken, setBroken] = useState(false)
  const [workbenchSrc, setWorkbenchSrc] = useState('')
  const workbenchRef = parseWorkbenchImageRef(imagePath)
  const legacyWorkbenchRef = parseLegacyWorkbenchOutputRef(imagePath)
  const workbenchLookup = workbenchRef || legacyWorkbenchRef
  const isWorkbenchRef = Boolean(workbenchLookup)
  const src = isWorkbenchRef ? workbenchSrc : resolveMediaAssetSrc(imagePath)

  useEffect(() => {
    let active = true
    let objectUrl = ''
    setBroken(false)
    if (!isWorkbenchRef) {
      setWorkbenchSrc('')
      return () => { active = false }
    }
    const match = parseWorkbenchImageRef(imagePath) || parseLegacyWorkbenchOutputRef(imagePath)
    if (!match) {
      setBroken(true)
      return () => { active = false }
    }
    ;(async () => {
      try {
        const base = await getGatewayBaseUrl()
        if (!base) throw new Error('Gateway unavailable')
        const token = getAuthToken()
        const headers: Record<string, string> = {}
        if (token) headers.Authorization = `Bearer ${token}`
        if (match.externalRef) headers['X-EvoFlow-External-Ref'] = match.externalRef
        const response = await fetch(
          `${base}/api/opsboard/image-preview/${encodeURIComponent(match.recordId)}/${match.itemIndex}`,
          { headers, cache: 'no-store', referrerPolicy: 'no-referrer' },
        )
        if (!response.ok) throw new Error(`Preview failed: ${response.status}`)
        objectUrl = URL.createObjectURL(await response.blob())
        if (active) setWorkbenchSrc(objectUrl)
      } catch {
        if (active) setBroken(true)
      }
    })()
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [imagePath, isWorkbenchRef])

  if (!imagePath) return null

  const title = alt || imagePath.split(/[\\/]/).pop() || '图片'

  return (
    <div
      className="msg-tool-block msg-tool-block--screenshot msg-tool-block--view-image"
      data-testid="view-image-inline-preview"
    >
      {broken ? (
        <p className="msg-tool-screenshot-error">图片预览失败，请检查路径是否可访问。</p>
      ) : !src ? (
        <p className="msg-tool-screenshot-summary">{isWorkbenchRef ? '正在读取工作台图片…' : '图片路径不可用。'}</p>
      ) : (
        <button
          type="button"
          className="msg-tool-screenshot-btn"
          title="放大查看"
          aria-label={`放大查看 ${title}`}
          onClick={() => showChatLightbox(src)}
        >
          <img
            className="msg-tool-screenshot-img"
            src={src}
            alt={title}
            loading="lazy"
            onError={(_e: SyntheticEvent<HTMLImageElement>) => setBroken(true)}
          />
          <span className="msg-tool-screenshot-hint">点击放大</span>
        </button>
      )}
      {caption ? <p className="msg-tool-screenshot-summary">{caption}</p> : null}
    </div>
  )
}

export const ViewImageInlinePreview = memo(ViewImageInlinePreviewInner)
