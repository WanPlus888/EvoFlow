import { useCallback, useEffect, useState } from 'react'
import { gatewayJson } from '../../lib/gateway-json.js'
import { draftTypeLabel, type WorkbenchOrderDraft } from '../lib/workbench-order-draft.js'

/**
 * AI 运营大脑 · 生产工单概览（P1 驾驶舱合一 + 1.4.4 待确认/跟单）。
 * 数据来自网关 /api/opsboard/*（服务端代理工作台），未配置或不可达时降级。
 */
type Summary = {
  configured?: boolean
  ok?: boolean
  detail?: string
  total?: number
  wait_review?: number
  running?: number
  approved?: number
  rejected?: number
  over_budget?: number
  spend?: number
}

type TrackOrder = {
  order_id?: string
  title?: string
  status?: string
  type?: string
  external_ref?: string
  review?: { status?: string }
}

export function OpsOrderSummary() {
  const [d, setD] = useState<Summary | null>(null)
  const [drafts, setDrafts] = useState<WorkbenchOrderDraft[]>([])
  const [busyRef, setBusyRef] = useState('')
  const [trackRef, setTrackRef] = useState('')
  const [tracked, setTracked] = useState<TrackOrder[]>([])
  const [trackMsg, setTrackMsg] = useState('')

  const loadSummary = useCallback(() => {
    gatewayJson('GET', '/opsboard/summary')
      .then((r) => setD(r as Summary))
      .catch((e) => setD({ configured: true, ok: false, detail: String(e) }))
  }, [])

  const loadDrafts = useCallback(() => {
    gatewayJson('GET', '/opsboard/drafts')
      .then((r) => {
        const rows = (r as { drafts?: WorkbenchOrderDraft[] })?.drafts
        setDrafts(Array.isArray(rows) ? rows : [])
      })
      .catch(() => setDrafts([]))
  }, [])

  useEffect(() => {
    let alive = true
    const tick = () => {
      if (!alive) return
      loadSummary()
      loadDrafts()
    }
    tick()
    const t = setInterval(tick, 60_000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [loadDrafts, loadSummary])

  if (!d || !d.configured) return null

  const go = () => {
    window.location.hash = '/extensions/ecom-ops-board'
  }

  const items: Array<{ label: string; value: string; tone?: string }> = [
    { label: '待验收', value: String(d.wait_review ?? 0), tone: 'warn' },
    { label: '生产中', value: String(d.running ?? 0) },
    { label: '已通过', value: String(d.approved ?? 0), tone: 'ok' },
    { label: '已打回', value: String(d.rejected ?? 0), tone: 'err' },
    { label: '超预算', value: String(d.over_budget ?? 0), tone: 'err' },
    { label: '估算花费', value: `¥${(d.spend ?? 0).toFixed(2)}` },
  ]

  const confirmDraft = async (draft: WorkbenchOrderDraft) => {
    const ref = String(draft.external_ref || '').trim()
    if (!ref || busyRef) return
    setBusyRef(ref)
    try {
      await gatewayJson('POST', '/opsboard/drafts', { draft })
      const res = (await gatewayJson(
        'POST',
        `/opsboard/drafts/${encodeURIComponent(ref)}/confirm`,
        {},
      )) as { result?: { deduped?: boolean; task_id?: string; error?: string; dispatched?: boolean } }
      const result = res?.result || {}
      if (result.dispatched === false && result.error) {
        setTrackMsg(`派单失败：${result.error}`)
      } else {
        setTrackMsg(
          result.deduped
            ? `${ref} 同号已派过，未重复扣费`
            : `${ref} 已确认派单${result.task_id ? ` · ${result.task_id}` : ''}`,
        )
        loadDrafts()
        loadSummary()
      }
    } catch (err) {
      setTrackMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyRef('')
    }
  }

  const doTrack = async () => {
    const ref = trackRef.trim()
    if (!ref) return
    setTrackMsg('查询中…')
    try {
      const res = (await gatewayJson(
        'GET',
        `/opsboard/orders/by-ref/${encodeURIComponent(ref)}`,
      )) as { ok?: boolean; orders?: TrackOrder[]; detail?: string; count?: number }
      setTracked(Array.isArray(res.orders) ? res.orders : [])
      setTrackMsg(
        res.ok === false
          ? res.detail || '查询失败'
          : `找到 ${res.count ?? 0} 条`,
      )
    } catch (err) {
      setTracked([])
      setTrackMsg(err instanceof Error ? err.message : String(err))
    }
  }

  const review = async (orderId: string, action: 'approve' | 'reject') => {
    const note =
      action === 'reject' ? window.prompt('打回原因（可空）') || '' : ''
    try {
      await gatewayJson(
        'POST',
        `/opsboard/orders/${encodeURIComponent(orderId)}/${action}`,
        { note },
      )
      setTrackMsg(`${action === 'approve' ? '已通过' : '已打回'} ${orderId}`)
      if (trackRef.trim()) void doTrack()
      loadSummary()
    } catch (err) {
      setTrackMsg(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <section className="evo-home-card evo-home-card--ops">
      <div className="evo-home-card__head">
        <div>
          <h2 className="evo-home-card__title">生产工单</h2>
          <p className="evo-home-card__hint" style={{ margin: '4px 0 0', fontSize: 12, opacity: 0.72 }}>
            工作台扣费派单口径；部门群「派工条 / 自动回执」只报告群内任务结果，不扣费。
          </p>
        </div>
        <button type="button" className="evo-home-btn evo-home-btn--chip" onClick={go}>
          去生产工单 →
        </button>
      </div>
      <div className="evo-home-card__body">
        {d.ok ? (
          <div className="evo-home-kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
            {items.map((it) => (
              <button type="button" key={it.label} className="evo-home-kpi" onClick={go}>
                <div className="evo-home-kpi__meta">
                  <div className="evo-home-kpi__label">{it.label}</div>
                  <div className="evo-home-kpi__value">{it.value}</div>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="evo-home-empty">工单数据不可达：{d.detail || ''}</div>
        )}

        <div className="uiext-ops-draft-bar" style={{ marginTop: 12, border: '1px solid #e2e8f0', borderRadius: 10 }}>
          <div className="uiext-ops-draft-bar__title">待确认派单（聊天草稿）</div>
          {drafts.length === 0 ? (
            <div className="uiext-ops-draft-bar__empty">暂无待确认草稿。员工用 draft_workbench_order 出草稿后会出现在这里。</div>
          ) : (
            drafts.map((draft) => {
              const ref = String(draft.external_ref || '')
              return (
                <div key={ref} className="uiext-ops-draft-row">
                  <div className="uiext-ops-draft-row__meta">
                    <div>
                      <strong>{draftTypeLabel(draft.type)}</strong>{' '}
                      {draft.product || draft.name || '未命名'}
                    </div>
                    <div className="uiext-ops-draft-row__ref">{ref}</div>
                  </div>
                  <button
                    type="button"
                    className="wb-order-draft-card__btn primary"
                    disabled={busyRef === ref}
                    onClick={() => void confirmDraft(draft)}
                  >
                    {busyRef === ref ? '派单中…' : '确认派单'}
                  </button>
                </div>
              )
            })
          )}

          <div className="uiext-ops-track">
            <div className="uiext-ops-draft-bar__title">按工单号跟单 / 验收</div>
            <div className="uiext-ops-track__row">
              <input
                className="search"
                style={{ width: 220 }}
                placeholder="EV-YYYYMMDD-HHMMSS"
                value={trackRef}
                onChange={(e) => setTrackRef(e.target.value)}
              />
              <button type="button" className="wb-order-draft-card__btn" onClick={() => void doTrack()}>
                查询
              </button>
            </div>
            {trackMsg ? <div className="wb-order-draft-card__hint">{trackMsg}</div> : null}
            {tracked.map((o) => (
              <div key={o.order_id} className="uiext-ops-draft-row">
                <div className="uiext-ops-draft-row__meta">
                  <div>
                    {o.title || o.order_id} · {o.status || '—'}
                    {o.review?.status ? ` · 验收 ${o.review.status}` : ''}
                  </div>
                  <div className="uiext-ops-draft-row__ref">{o.external_ref}</div>
                </div>
                {!o.review?.status && o.order_id ? (
                  <>
                    <button
                      type="button"
                      className="wb-order-draft-card__btn"
                      onClick={() => void review(String(o.order_id), 'approve')}
                    >
                      ✓ 通过
                    </button>
                    <button
                      type="button"
                      className="wb-order-draft-card__btn"
                      onClick={() => void review(String(o.order_id), 'reject')}
                    >
                      ✗ 打回
                    </button>
                  </>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
