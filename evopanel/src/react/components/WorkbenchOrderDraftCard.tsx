import { memo, useCallback, useState } from 'react'
import { gatewayJson } from '../../lib/gateway-json.js'
import {
  draftTypeLabel,
  type WorkbenchOrderDraft,
} from '../lib/workbench-order-draft.js'

type Props = {
  draft: WorkbenchOrderDraft
  className?: string
}

type ConfirmState = 'idle' | 'loading' | 'done' | 'error'

/**
 * 聊天内「确认派单」卡：人点才调网关 confirm → 工作台 dispatch。
 */
export const WorkbenchOrderDraftCard = memo(function WorkbenchOrderDraftCard({
  draft,
  className = '',
}: Props) {
  const ref = String(draft.external_ref || '').trim()
  const [state, setState] = useState<ConfirmState>(
    draft.status === 'confirmed' ? 'done' : 'idle',
  )
  const [message, setMessage] = useState('')
  const [taskId, setTaskId] = useState('')
  const needsConfirm = Boolean(draft.needs_confirm)

  const onConfirm = useCallback(async () => {
    if (!ref || state === 'loading' || state === 'done') return
    setState('loading')
    setMessage('')
    try {
      // 先 upsert，保证服务端有草稿（即使工具落库失败也能确认）
      await gatewayJson('POST', '/opsboard/drafts', { draft })
      const res = (await gatewayJson(
        'POST',
        `/opsboard/drafts/${encodeURIComponent(ref)}/confirm`,
        {},
      )) as { ok?: boolean; result?: { task_id?: string; deduped?: boolean; error?: string; dispatched?: boolean } }
      const result = res?.result || {}
      if (result.dispatched === false && result.error) {
        setState('error')
        setMessage(String(result.error))
        return
      }
      setTaskId(String(result.task_id || ''))
      setMessage(result.deduped ? '同号已派过，未重复扣费' : '已确认派单')
      setState('done')
    } catch (err) {
      setState('error')
      setMessage(err instanceof Error ? err.message : String(err))
    }
  }, [draft, ref, state])

  const goBoard = () => {
    window.location.hash = '/extensions/ecom-ops-board'
  }

  return (
    <div className={`wb-order-draft-card ${className}`.trim()} data-testid="wb-order-draft-card">
      <div className="wb-order-draft-card__head">
        <strong>工单草稿</strong>
        <span className="wb-order-draft-card__pill">{draftTypeLabel(draft.type)}</span>
        {ref ? <code className="wb-order-draft-card__ref">{ref}</code> : null}
      </div>
      <dl className="wb-order-draft-card__meta">
        {draft.product ? (
          <>
            <dt>产品</dt>
            <dd>{draft.product}</dd>
          </>
        ) : null}
        {draft.qty ? (
          <>
            <dt>数量</dt>
            <dd>{draft.qty}</dd>
          </>
        ) : null}
        {draft.budget ? (
          <>
            <dt>预算</dt>
            <dd>¥{draft.budget}</dd>
          </>
        ) : null}
        {draft.assigned_role ? (
          <>
            <dt>岗位</dt>
            <dd>{draft.assigned_role}</dd>
          </>
        ) : null}
      </dl>
      {needsConfirm ? (
        <p className="wb-order-draft-card__warn">
          字段不齐（{(draft.needs_confirm_fields || []).join('、') || '待确认'}），建议补全后再派单。
        </p>
      ) : null}
      <div className="wb-order-draft-card__actions">
        <button
          type="button"
          className="wb-order-draft-card__btn primary"
          disabled={!ref || state === 'loading' || state === 'done'}
          onClick={() => void onConfirm()}
        >
          {state === 'loading' ? '派单中…' : state === 'done' ? '已派单' : '确认派单'}
        </button>
        <button type="button" className="wb-order-draft-card__btn" onClick={goBoard}>
          去生产工单
        </button>
      </div>
      {message ? (
        <p className={`wb-order-draft-card__msg ${state === 'error' ? 'is-err' : 'is-ok'}`}>
          {message}
          {taskId ? ` · 任务 ${taskId}` : ''}
        </p>
      ) : (
        <p className="wb-order-draft-card__hint">未点确认前不会扣费；同工单号不会双扣。</p>
      )}
    </div>
  )
})
