/**
 * 解析 draft_workbench_order 工具输出，供聊天确认卡 / 生产工单页复用。
 */

export type WorkbenchOrderDraft = {
  status?: string
  type?: string
  external_ref?: string
  product?: string
  qty?: string
  budget?: string
  due?: string
  name?: string
  description?: string
  acceptance?: string
  assigned_role?: string
  needs_confirm?: boolean
  needs_confirm_fields?: string[]
  next_step?: string
  source_text?: string
}

export function parseWorkbenchOrderDraftOutput(output: unknown): WorkbenchOrderDraft | null {
  let raw: unknown = output
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    const obj = raw as Record<string, unknown>
    if (typeof obj.content === 'string') raw = obj.content
    else if (typeof obj.output === 'string') raw = obj.output
    else if (typeof obj.result === 'string') raw = obj.result
    else if (obj.external_ref || obj.status === 'draft') return obj as WorkbenchOrderDraft
  }
  if (typeof raw !== 'string') return null
  const text = raw.trim()
  if (!text) return null
  // 工具结果可能包在 markdown fence 或前后缀里
  const fence = text.match(/\{[\s\S]*\}/)
  const jsonText = fence ? fence[0] : text
  try {
    const parsed = JSON.parse(jsonText) as WorkbenchOrderDraft
    if (!parsed || typeof parsed !== 'object') return null
    if (parsed.status && parsed.status !== 'draft' && parsed.status !== 'confirmed') {
      // 仍允许带 external_ref 的草稿形态
      if (!parsed.external_ref) return null
    }
    if (!parsed.external_ref && !parsed.type) return null
    return parsed
  } catch {
    return null
  }
}

export function isWorkbenchOrderDraftTool(toolKind: string, toolName?: string): boolean {
  const k = String(toolKind || '').trim()
  const n = String(toolName || '').trim()
  return k === 'draft_workbench_order' || n === 'draft_workbench_order'
}

export function draftTypeLabel(type?: string): string {
  switch (String(type || '')) {
    case 'image':
      return '套图'
    case 'video':
      return '短视频'
    case 'tuwen':
      return '图文带货'
    default:
      return '自定义'
  }
}
