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
  binder_ready: '/working-papers',
  binder_untied: '/working-papers',
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

      <div className="grid-2" style={{ marginBottom: '0.85rem' }}>
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
        {data.binder_summary && (
          <section className="panel close-summary-banner">
            <div>
              <strong>Binder {data.binder_summary.period_label}</strong>
              <p className="hint">
                {data.binder_summary.prepared}/{data.binder_summary.total} prepared ·{' '}
                {data.binder_summary.reviewed} reviewed · {data.binder_summary.untied} untied leads
              </p>
            </div>
            <Link className="btn primary" to={data.binder_summary.href}>
              Open binder <ArrowRight size={14} />
            </Link>
          </section>
        )}
      </div>

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
          const binder = data.binder_summary
          let href = closeHref
          if (kpi.key === 'binder_ready' || kpi.key === 'binder_untied') {
            href = binder?.href ?? '/working-papers'
          } else if (
            kpi.key !== 'close_progress' &&
            kpi.key !== 'blocking_exceptions' &&
            kpi.key !== 'outstanding_reconciliations'
          ) {
            href = `${JOB_KPI_HREF[kpi.key]}${summary ? `&year=${summary.period_year}&month=${summary.period_month}` : ''}`
          }
          return (
            <Link
              key={kpi.key}
              to={href}
              className={`kpi ${kpi.status === 'warning' ? 'warn' : kpi.status === 'ok' ? 'ok' : ''} kpi-drillable`}
              title={kpi.key.startsWith('binder') ? 'Open binder' : 'Open Close cockpit'}
            >
              <div className="kpi-label">
                {kpi.label}
                <span className="drill-cue">↗</span>
              </div>
              <div className="kpi-value">
                {kpi.key === 'close_progress' && summary
                  ? `${summary.banks_locked}/${summary.banks_total}`
                  : kpi.key === 'binder_ready' && binder
                    ? `${binder.prepared}/${binder.total}`
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

      <section className="panel recon-health-panel">
        <div className="panel-header">
          <h2>Reconciliation health</h2>
          <span className="hint">Account · balance · last reconciled · vs budget</span>
        </div>
        <div className="table-wrap">
          <table className="data recon-health-table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Entity</th>
                <th className="num">Balance</th>
                <th className="num">Budget</th>
                <th className="num">Variance</th>
                <th>Target</th>
                <th>Last reconciled</th>
                <th>This month</th>
              </tr>
            </thead>
            <tbody>
              {(data.recon_health ?? []).length === 0 && (
                <tr>
                  <td colSpan={8} className="hint">
                    No bank accounts yet.
                  </td>
                </tr>
              )}
              {(data.recon_health ?? []).map((row) => {
                const targetClass =
                  row.target_status === 'on_target'
                    ? 'ok'
                    : row.target_status === 'no_budget'
                      ? ''
                      : 'open'
                const freshClass =
                  row.recon_freshness === 'current' || row.recon_freshness === 'prior'
                    ? 'ok'
                    : 'open'
                const targetLabel =
                  row.target_status === 'on_target'
                    ? 'On target'
                    : row.target_status === 'above'
                      ? 'Above budget'
                      : row.target_status === 'below'
                        ? 'Below budget'
                        : 'No budget'
                const lastLabel = row.last_reconciled_date
                  ? `${row.last_reconciled_date}${
                      row.days_since_reconciled != null ? ` · ${row.days_since_reconciled}d` : ''
                    }`
                  : 'Never'
                return (
                  <tr key={row.bank_account_id} className={`recon-health-row ${row.target_status}`}>
                    <td>
                      <Link to={row.href}>{row.name}</Link>
                      <div className="hint">{row.currency}</div>
                    </td>
                    <td>
                      <span className="badge">{row.entity_code}</span>
                    </td>
                    <td className="num">{money(row.balance, row.currency)}</td>
                    <td className="num">
                      {row.budget_balance == null ? '—' : money(row.budget_balance, row.currency)}
                    </td>
                    <td className="num">
                      {row.variance == null ? (
                        '—'
                      ) : (
                        <>
                          {money(row.variance, row.currency)}
                          {row.variance_pct != null && (
                            <div className="hint">{Number(row.variance_pct).toFixed(1)}%</div>
                          )}
                        </>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${targetClass}`}>{targetLabel}</span>
                    </td>
                    <td>
                      <span className={`badge ${freshClass}`}>{lastLabel}</span>
                      {row.last_reconciled_period && (
                        <div className="hint">{row.last_reconciled_period}</div>
                      )}
                    </td>
                    <td>
                      <span
                        className={`badge ${row.current_period_status === 'locked' ? 'ok' : row.current_period_status === 'not_started' ? '' : 'open'}`}
                      >
                        {row.current_period_status.replace('_', ' ')}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <h2>FX exposure</h2>
          </div>
          <div className="table-wrap" style={{ maxHeight: 220 }}>
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
          <div className="table-wrap" style={{ maxHeight: 220 }}>
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
