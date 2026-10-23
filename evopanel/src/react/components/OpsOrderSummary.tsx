import { useEffect, useState } from 'react'
import { gatewayJson } from '../../lib/gateway-json.js'

/**
 * 电商运营终端 · 生产工单概览（P1 驾驶舱合一，fork 扩展）。
 * 数据来自网关 /api/opsboard/summary（服务端代理工作台），未配置或不可达时降级。
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

export function OpsOrderSummary() {
  const [d, setD] = useState<Summary | null>(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      gatewayJson('GET', '/opsboard/summary')
        .then((r) => { if (alive) setD(r as Summary) })
        .catch((e) => { if (alive) setD({ configured: true, ok: false, detail: String(e) }) })
    load()
    const t = setInterval(load, 60_000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  if (!d || !d.configured) return null

  const go = () => { window.location.hash = '/extensions/ecom-ops-board' }

  const items: Array<{ label: string; value: string; tone?: string }> = [
    { label: '待验收', value: String(d.wait_review ?? 0), tone: 'warn' },
    { label: '生产中', value: String(d.running ?? 0) },
    { label: '已通过', value: String(d.approved ?? 0), tone: 'ok' },
    { label: '已打回', value: String(d.rejected ?? 0), tone: 'err' },
    { label: '超预算', value: String(d.over_budget ?? 0), tone: 'err' },
    { label: '估算花费', value: `¥${(d.spend ?? 0).toFixed(2)}` },
  ]

  return (
    <section className="evo-home-card evo-home-card--ops">
      <div className="evo-home-card__head">
        <h2 className="evo-home-card__title">生产工单</h2>
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
      </div>
    </section>
  )
}
