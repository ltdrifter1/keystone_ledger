import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download } from 'lucide-react'
import { api, type AnalyticsPack, type ReportFilters } from '../api'
import { money } from '../lib/format'
import { useEngagement } from '../period/PeriodContext'

function periodEndIso(year: number, month: number) {
  const d = new Date(year, month, 0)
  return d.toISOString().slice(0, 10)
}

export function AnalyticsPage({ embedded = false }: { embedded?: boolean }) {
  const { year, month, label, entityId, entityCode } = useEngagement()
  const [pack, setPack] = useState<AnalyticsPack | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const filters: ReportFilters = useMemo(
    () => ({
      report_type: 'income_statement',
      period: 'monthly',
      year,
      month,
      scenario_id: 1,
      reporting_currency: 'CAD',
      consolidate: !entityId,
      entity_ids: entityId ? [Number(entityId)] : null,
      as_of_date: periodEndIso(year, month),
      date_to: periodEndIso(year, month),
      compare_prior_period: true,
      compare_prior_year: true,
      compare_budget: true,
    }),
    [year, month, entityId],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setPack(await api.analytics(filters))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div>
      {!embedded && (
        <div className="page-header">
          <div>
            <h1>Analytics</h1>
            <p>
              CaseWare-style analytical review for {entityCode ?? 'entity'} · {label}.
            </p>
          </div>
        </div>
      )}
      {embedded && (
        <div className="toolbar" style={{ marginBottom: '0.85rem' }}>
          <span className="hint">
            Material flux vs prior period / prior year / budget for this month. Materiality{' '}
            {pack ? `${money(pack.materiality_amount)} or ${Number(pack.materiality_pct)}%` : '…'}.
          </span>
          <button className="btn" onClick={() => void api.exportStatements(filters)} disabled={loading}>
            <Download size={14} /> Export pack
          </button>
          <button className="btn" onClick={() => void load()} disabled={loading}>
            {loading ? 'Running…' : 'Refresh'}
          </button>
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {pack && (
        <div className="kpi-grid">
          {pack.kpis.map((k) => (
            <div key={k.key} className={`kpi ${k.tone === 'ok' ? 'ok' : k.tone === 'warn' ? 'warn' : ''}`}>
              <div className="kpi-label">{k.label}</div>
              <div className="kpi-value">{money(k.amount)}</div>
              {k.variance != null && (
                <div className="hint">
                  vs prior {money(k.variance)}
                  {k.variance_pct != null ? ` (${Number(k.variance_pct).toFixed(1)}%)` : ''}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <section className="panel" style={{ marginTop: '1rem' }}>
        <div className="panel-header">
          <h2>Material movements</h2>
          <span className="hint">{pack?.flux.length ?? 0} flagged lines across IS / BS / CF</span>
        </div>
        {!pack?.flux.length && !loading && <p className="hint">No material flux this period.</p>}
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Stmt</th>
                <th>Ref</th>
                <th>Line</th>
                <th>Flag</th>
                <th>Commentary</th>
                <th className="num">Current</th>
                <th className="num">Var</th>
              </tr>
            </thead>
            <tbody>
              {pack?.flux.map((item) => (
                <tr key={`${item.report_type}-${item.line_code}`}>
                  <td>
                    <span className="badge">{item.report_type.replace('_', ' ')}</span>
                  </td>
                  <td className="wp-col">{item.wp_ref ?? ''}</td>
                  <td>
                    {item.drillable ? (
                      <Link
                        to={`/statements?tab=statement&year=${year}&month=${month}&line=${item.line_code}&type=${item.report_type}`}
                      >
                        {item.line_label}
                      </Link>
                    ) : (
                      item.line_label
                    )}
                  </td>
                  <td>
                    <span className={`badge ${item.flag === 'material' ? 'open' : 'ok'}`}>{item.flag}</span>
                  </td>
                  <td className="hint">{item.note}</td>
                  <td className="num">{money(item.amount)}</td>
                  <td className="num">{item.variance != null ? money(item.variance) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
