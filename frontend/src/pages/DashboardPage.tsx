import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2 } from 'lucide-react'
import { api, type Dashboard, type DrillOut } from '../api'
import { WorkingPaperDrawer } from '../components/WorkingPaperDrawer'
import { money } from '../lib/format'

const KPI_DRILL: Record<string, { line_code: string; label: string }> = {
  revenue: { line_code: 'TOT_REV', label: 'Total Revenue' },
  expenses: { line_code: 'TOT_EXP', label: 'Total Expenses' },
  net_income: { line_code: 'NI', label: 'Net Income' },
}

const JOB_KPI_HREF: Record<string, string> = {
  close_progress: '/close',
  outstanding_reconciliations: '/close',
  uncategorized: '/close?filter=uncategorized',
  unmatched_ic: '/close?filter=intercompany',
  blocking_exceptions: '/close',
}

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drill, setDrill] = useState<DrillOut | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillError, setDrillError] = useState<string | null>(null)

  useEffect(() => {
    api
      .dashboard('CAD')
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [])

  const openKpiDrill = async (key: string) => {
    const map = KPI_DRILL[key]
    if (!map) return
    setDrawerOpen(true)
    setDrillLoading(true)
    setDrillError(null)
    try {
      const report = await api.report({
        report_type: 'income_statement',
        period: 'ytd',
        year: new Date().getFullYear(),
        scenario_id: 1,
        reporting_currency: 'CAD',
        consolidate: true,
      })
      let line = report.lines.find((l) => l.line_code === map.line_code)
      if (!line && key === 'net_income') {
        line = report.lines.find((l) => l.line_code === 'NET_INCOME' || l.line_label === 'Net Income')
      }
      if (!line && key === 'revenue') {
        line = report.lines.find((l) => l.line_code.includes('REV') && l.is_total)
      }
      if (!line && key === 'expenses') {
        line = report.lines.find((l) => l.line_code.includes('EXP') && l.is_total)
      }
      if (!line?.drillable) {
        throw new Error('No drillable statement line for this KPI')
      }
      const res = await api.drillReport({
        line_code: line.line_code,
        account_id: line.account_id,
        account_ids: line.account_ids,
        account_type_filter: line.account_type_filter,
        filters: {
          report_type: 'income_statement',
          period: 'ytd',
          year: new Date().getFullYear(),
          scenario_id: 1,
          reporting_currency: 'CAD',
          consolidate: true,
        },
      })
      setDrill(res)
    } catch (e) {
      setDrill(null)
      setDrillError((e as Error).message)
    } finally {
      setDrillLoading(false)
    }
  }

  if (error) return <div className="error">{error}</div>
  if (!data) return <p className="hint">Loading dashboard…</p>

  const summary = data.close_summary
  const closeHref = summary
    ? `/close?year=${summary.period_year}&month=${summary.period_month}`
    : '/close'
  const jobKeys = new Set(Object.keys(JOB_KPI_HREF))
  const jobKpis = data.kpis.filter((k) => jobKeys.has(k.key))
  const contextKpis = data.kpis.filter((k) => !jobKeys.has(k.key))

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p>
            {summary
              ? `${summary.period_label}: ${summary.banks_locked}/${summary.banks_total} banks locked · ${summary.blocking_total} blocking`
              : 'Close progress and what to do next.'}
          </p>
        </div>
        <div className="toolbar">
          <Link className="btn primary" to={closeHref}>
            Open Close cockpit
          </Link>
        </div>
      </div>

      {summary && (
        <section className="panel close-summary-banner">
          <div>
            <strong>Month-end {summary.period_label}</strong>
            <p className="hint">
              {summary.all_locked
                ? 'All banks locked for this period.'
                : `${summary.banks_ready_to_lock} ready to lock · ${summary.banks_in_progress} in progress · ${summary.blocking_total} blocking exceptions`}
            </p>
          </div>
          <Link className="btn primary" to={closeHref}>
            {summary.all_locked ? (
              <>
                <CheckCircle2 size={14} /> View close
              </>
            ) : (
              <>
                Continue close <ArrowRight size={14} />
              </>
            )}
          </Link>
        </section>
      )}

      {(data.next_actions?.length ?? 0) > 0 && (
        <section className="panel" style={{ marginBottom: '0.85rem' }}>
          <div className="panel-header">
            <h2>Next actions</h2>
            <span className="hint">Deep-links into Close</span>
          </div>
          <div className="close-next-list" style={{ padding: '0.75rem' }}>
            {data.next_actions!.slice(0, 6).map((action) => (
              <Link
                key={action.key}
                to={action.href}
                className={`close-next-card ${action.status === 'ok' ? 'ok' : 'warn'}`}
              >
                <div>
                  <strong>{action.title}</strong>
                  <span className="hint">{action.detail}</span>
                </div>
                <ArrowRight size={16} />
              </Link>
            ))}
          </div>
        </section>
      )}

      <div className="kpi-grid" style={{ marginBottom: '0.65rem' }}>
        {jobKpis.map((kpi) => {
          const href =
            kpi.key === 'close_progress' || kpi.key === 'blocking_exceptions' || kpi.key === 'outstanding_reconciliations'
              ? closeHref
              : `${JOB_KPI_HREF[kpi.key]}${summary ? `&year=${summary.period_year}&month=${summary.period_month}` : ''}`
          return (
            <Link
              key={kpi.key}
              to={href}
              className={`kpi ${kpi.status === 'warning' ? 'warn' : kpi.status === 'ok' ? 'ok' : ''} kpi-drillable`}
              title="Open Close cockpit"
            >
              <div className="kpi-label">
                {kpi.label}
                <span className="drill-cue">↗</span>
              </div>
              <div className="kpi-value">
                {kpi.key === 'close_progress' && summary
                  ? `${summary.banks_locked}/${summary.banks_total}`
                  : kpi.format === 'number'
                    ? Number(kpi.value).toLocaleString()
                    : money(kpi.value, kpi.currency)}
              </div>
            </Link>
          )
        })}
      </div>

      <div className="kpi-grid">
        {contextKpis.map((kpi) => {
          const drillable = Boolean(KPI_DRILL[kpi.key])
          return (
            <div
              key={kpi.key}
              className={`kpi ${kpi.status === 'warning' ? 'warn' : kpi.status === 'ok' ? 'ok' : ''} ${drillable ? 'kpi-drillable' : ''}`}
              onClick={() => drillable && void openKpiDrill(kpi.key)}
              title={drillable ? 'Open working paper' : undefined}
            >
              <div className="kpi-label">
                {kpi.label}
                {drillable && <span className="drill-cue">↗</span>}
              </div>
              <div className="kpi-value">
                {kpi.format === 'number' ? Number(kpi.value).toLocaleString() : money(kpi.value, kpi.currency)}
              </div>
            </div>
          )
        })}
      </div>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <h2>Cash by account</h2>
            <Link className="btn ghost" to={closeHref}>
              Reconcile
            </Link>
          </div>
          <div className="table-wrap" style={{ maxHeight: 360 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Entity</th>
                  <th className="num">Native</th>
                  <th className="num">CAD</th>
                </tr>
              </thead>
              <tbody>
                {data.cash_by_account.map((row) => (
                  <tr key={row.bank_account_id}>
                    <td>
                      <Link to={`${closeHref}&bank=${row.bank_account_id}`}>{row.name}</Link>
                    </td>
                    <td>
                      <span className="badge">{row.entity_code}</span>
                    </td>
                    <td className="num">{money(row.balance, row.currency)}</td>
                    <td className="num">{money(row.balance_reporting)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div style={{ display: 'grid', gap: '0.85rem' }}>
          <section className="panel">
            <div className="panel-header">
              <h2>FX exposure</h2>
            </div>
            <div className="table-wrap" style={{ maxHeight: 180 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>CCY</th>
                    <th className="num">Native</th>
                    <th className="num">Rate</th>
                    <th className="num">CAD</th>
                  </tr>
                </thead>
                <tbody>
                  {data.fx_exposure.map((row) => (
                    <tr key={String(row.currency)}>
                      <td>{row.currency}</td>
                      <td className="num">{money(row.native_balance as number)}</td>
                      <td className="num">{Number(row.rate).toFixed(4)}</td>
                      <td className="num">{money(row.reporting_balance as number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Intercompany balances</h2>
              <Link className="btn ghost" to={`${closeHref}&filter=intercompany`}>
                Match
              </Link>
            </div>
            <div className="table-wrap" style={{ maxHeight: 180 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>From</th>
                    <th>To</th>
                    <th className="num">Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {data.intercompany_balances.length === 0 && (
                    <tr>
                      <td colSpan={3} className="hint">
                        No open intercompany balances
                      </td>
                    </tr>
                  )}
                  {data.intercompany_balances.map((row, i) => (
                    <tr key={i}>
                      <td>{row.from_entity}</td>
                      <td>{row.to_entity}</td>
                      <td className="num">{money(row.balance as number, String(row.currency))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>

      <WorkingPaperDrawer
        open={drawerOpen}
        loading={drillLoading}
        error={drillError}
        data={drill}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  )
}
