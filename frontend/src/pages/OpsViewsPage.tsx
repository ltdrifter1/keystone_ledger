import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api,
  type BudgetView,
  type Entity,
  type ExpensesView,
  type OpsKpi,
  type OpsLine,
  type SalesView,
} from '../api'
import { money } from '../lib/format'
import { usePeriod } from '../period/PeriodContext'

type Mode = 'sales' | 'expenses' | 'budget'

function KpiCards({ kpis }: { kpis: OpsKpi[] }) {
  if (!kpis.length) return null
  return (
    <div className="kpi-grid">
      {kpis.map((k) => (
        <div key={k.key} className={`kpi ${k.tone === 'ok' ? 'ok' : k.tone === 'warn' ? 'warn' : ''}`}>
          <div className="kpi-label">{k.label}</div>
          <div className="kpi-value">{money(k.amount)}</div>
          {k.variance != null && (
            <div className="hint">
              vs budget {money(k.variance)}
              {k.variance_pct != null ? ` (${k.variance_pct.toFixed(1)}%)` : ''}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function LinesTable({
  lines,
  showCompare,
}: {
  lines: OpsLine[]
  showCompare: boolean
}) {
  if (!lines.length) {
    return <p className="hint">No lines for this period / entity.</p>
  }
  return (
    <div className="table-wrap">
      <table className="data statement-table">
        <thead>
          <tr>
            <th>Line</th>
            <th className="num">Actual</th>
            {showCompare && <th className="num">Budget</th>}
            {showCompare && <th className="num">Variance</th>}
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.line_code} className={line.is_total || line.is_bold ? 'total-row' : ''}>
              <td style={{ paddingLeft: `${0.75 + line.indent_level * 0.85}rem` }}>
                {line.href ? <Link to={line.href}>{line.line_label}</Link> : line.line_label}
                {line.wp_ref && <span className="hint"> · {line.wp_ref}</span>}
              </td>
              <td className="num">{money(line.amount)}</td>
              {showCompare && (
                <td className="num">{line.compare_amount == null ? '—' : money(line.compare_amount)}</td>
              )}
              {showCompare && (
                <td className="num">{line.variance == null ? '—' : money(line.variance)}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function OpsViewPage({ mode }: { mode: Mode }) {
  const { year, month, label } = usePeriod()
  const [entities, setEntities] = useState<Entity[]>([])
  const [entityId, setEntityId] = useState('')
  const [period, setPeriod] = useState('ytd')
  const [sales, setSales] = useState<SalesView | null>(null)
  const [expenses, setExpenses] = useState<ExpensesView | null>(null)
  const [budget, setBudget] = useState<BudgetView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.entities().then((e) => {
      setEntities(e)
      const can = e.find((x) => x.code === 'CAN')
      if (can) setEntityId(String(can.id))
    })
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const eid = entityId ? Number(entityId) : undefined
      if (mode === 'sales') {
        setSales(await api.salesView({ year, month, entity_id: eid, period }))
      } else if (mode === 'expenses') {
        setExpenses(await api.expensesView({ year, month, entity_id: eid, period }))
      } else {
        setBudget(await api.budgetView({ year, month, entity_id: eid, period }))
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [mode, year, month, entityId, period])

  useEffect(() => {
    void load()
  }, [load])

  const title = mode === 'sales' ? 'Sales' : mode === 'expenses' ? 'Expenses' : 'Budget overview'
  const blurb =
    mode === 'sales'
      ? 'Quick read of revenue, channels, and sales vs budget for the engagement period.'
      : mode === 'expenses'
        ? 'COGS, operating spend, and expense vs budget — filtered by entity.'
        : 'P&L actual vs budget plus cash targets by bank. CAN and USA stay separate.'

  const kpis =
    mode === 'sales' ? sales?.kpis : mode === 'expenses' ? expenses?.kpis : budget?.pnl_kpis
  const lines =
    mode === 'sales' ? sales?.lines : mode === 'expenses' ? expenses?.lines : budget?.pnl_lines
  const showCompare = Boolean(
    (mode === 'sales' && sales?.kpis.some((k) => k.compare_amount != null)) ||
      (mode === 'expenses' && expenses?.kpis.some((k) => k.compare_amount != null)) ||
      (mode === 'budget' && budget?.budget_facts_ready),
  )

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>{title}</h1>
          <p>
            {blurb} Period {label}.
          </p>
        </div>
        <div className="toolbar">
          <select className="select" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="monthly">Monthly</option>
            <option value="ytd">YTD</option>
            <option value="quarterly">Quarterly</option>
          </select>
          <select className="select" value={entityId} onChange={(e) => setEntityId(e.target.value)}>
            <option value="">All entities (sum)</option>
            {entities.map((e) => (
              <option key={e.id} value={e.id}>
                {e.code} — {e.name}
              </option>
            ))}
          </select>
          <button className="btn" onClick={() => void load()} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {kpis && <KpiCards kpis={kpis} />}

      {mode === 'sales' && sales && sales.top_channels.length > 0 && (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <div className="panel-header">
            <h2>Top channels</h2>
            <span className="hint">YTD / period department roll-up</span>
          </div>
          <LinesTable lines={sales.top_channels} showCompare={false} />
        </section>
      )}

      <section className="panel" style={{ marginTop: '1rem' }}>
        <div className="panel-header">
          <h2>{mode === 'budget' ? 'P&L vs budget' : `${title} detail`}</h2>
          <span className="hint">
            {showCompare ? 'Actual vs budget' : 'Actual'} ·{' '}
            <Link to="/reports?type=income_statement">Open full report</Link>
          </span>
        </div>
        {lines && <LinesTable lines={lines} showCompare={showCompare} />}
      </section>

      {mode === 'budget' && budget && (
        <section className="panel recon-health-panel" style={{ marginTop: '1rem' }}>
          <div className="panel-header">
            <h2>Cash vs target</h2>
            <span className="hint">
              {budget.budget_facts_ready
                ? 'Bank book balance vs budget_balance'
                : 'P&L budget facts not ready — cash targets still shown'}
            </span>
          </div>
          <div className="table-wrap">
            <table className="data recon-health-table">
              <thead>
                <tr>
                  <th>Bank</th>
                  <th className="num">Book</th>
                  <th className="num">Budget</th>
                  <th className="num">Variance</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {budget.cash_rows.map((row) => (
                  <tr key={row.bank_account_id} className={`recon-health-row ${row.status}`}>
                    <td>
                      <strong>{row.bank_account_name}</strong>
                      <div className="hint">
                        {row.entity_code} · {row.currency}
                      </div>
                    </td>
                    <td className="num">{money(row.book_balance, row.currency)}</td>
                    <td className="num">
                      {row.budget_balance == null ? '—' : money(row.budget_balance, row.currency)}
                    </td>
                    <td className="num">{row.variance == null ? '—' : money(row.variance, row.currency)}</td>
                    <td>
                      <span className={`badge ${row.status === 'on_target' ? 'ok' : 'open'}`}>
                        {row.status.replace('_', ' ')}
                      </span>
                    </td>
                    <td>
                      <Link className="btn ghost" to={row.href}>
                        Close
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

export function SalesPage() {
  return <OpsViewPage mode="sales" />
}

export function ExpensesPage() {
  return <OpsViewPage mode="expenses" />
}

export function BudgetPage() {
  return <OpsViewPage mode="budget" />
}
