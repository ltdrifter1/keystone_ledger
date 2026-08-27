import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type DrillOut, type Entity, type Report, type ReportFilters, type ReportLine, type Scenario } from '../api'
import { WorkingPaperDrawer } from '../components/WorkingPaperDrawer'
import { money } from '../lib/format'
import { useEngagement } from '../period/PeriodContext'
import { Download } from 'lucide-react'

function periodEndIso(year: number, month: number) {
  const d = new Date(year, month, 0)
  return d.toISOString().slice(0, 10)
}

export function ReportsPage() {
  const {
    year,
    month,
    setPeriod: setEngagementPeriod,
    label,
    entityId: engagementEntityId,
    setEntityId: setEngagementEntityId,
    entityCode,
  } = useEngagement()
  const [searchParams] = useSearchParams()
  const initialType = searchParams.get('type') || 'income_statement'
  const [reportType, setReportType] = useState(
    ['income_statement', 'balance_sheet', 'cash_flow'].includes(initialType)
      ? initialType
      : 'income_statement',
  )
  const [reportPeriod, setReportPeriod] = useState(
    searchParams.get('type') === 'balance_sheet' ? 'monthly' : 'ytd',
  )
  const [entityId, setEntityIdLocal] = useState(engagementEntityId || '')
  const [scenarioId, setScenarioId] = useState('1')
  const [compareScenarioId, setCompareScenarioId] = useState('')
  const [comparePrior, setComparePrior] = useState(true)
  const [compareYear, setCompareYear] = useState(true)
  const [compareBudget, setCompareBudget] = useState(true)
  const [entities, setEntities] = useState<Entity[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeLine, setActiveLine] = useState<string | null>(null)
  const [drill, setDrill] = useState<DrillOut | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillError, setDrillError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEffect(() => {
    Promise.all([api.entities(), api.scenarios()]).then(([e, s]) => {
      setEntities(e)
      setScenarios(s)
    })
  }, [])

  useEffect(() => {
    if (engagementEntityId) setEntityIdLocal(engagementEntityId)
  }, [engagementEntityId])

  const setEntityId = (id: string) => {
    setEntityIdLocal(id)
    if (id) setEngagementEntityId(id)
  }

  useEffect(() => {
    const t = searchParams.get('type')
    if (t && ['income_statement', 'balance_sheet', 'cash_flow'].includes(t)) {
      setReportType(t)
      if (t === 'balance_sheet') setReportPeriod('monthly')
    }
    const y = searchParams.get('year')
    const m = searchParams.get('month')
    if (y && m) setEngagementPeriod(Number(y), Number(m))
  }, [searchParams, setEngagementPeriod])

  const asOf = periodEndIso(year, month)

  const filters: ReportFilters = useMemo(
    () => ({
      report_type: reportType,
      period: reportType === 'balance_sheet' ? 'monthly' : reportPeriod,
      year,
      month,
      scenario_id: Number(scenarioId),
      reporting_currency: 'CAD',
      consolidate: !entityId,
      entity_ids: entityId ? [Number(entityId)] : null,
      compare_scenario_id: compareScenarioId ? Number(compareScenarioId) : null,
      as_of_date: asOf,
      date_to: asOf,
      compare_prior_period: comparePrior,
      compare_prior_year: compareYear,
      compare_budget: compareBudget,
    }),
    [reportType, reportPeriod, year, month, scenarioId, entityId, compareScenarioId, asOf, comparePrior, compareYear, compareBudget],
  )

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.report(filters)
      setReport(res)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    void run()
  }, [run])

  const openDrill = async (line: ReportLine) => {
    if (!line.drillable) return
    setActiveLine(line.line_code)
    setDrawerOpen(true)
    setDrillLoading(true)
    setDrillError(null)
    try {
      const res = await api.drillReport({
        line_code: line.line_code,
        account_id: line.account_id,
        account_ids: line.account_ids,
        account_type_filter: line.account_type_filter,
        filters,
      })
      setDrill(res)
    } catch (e) {
      setDrill(null)
      setDrillError((e as Error).message)
    } finally {
      setDrillLoading(false)
    }
  }

  // Deep-link from binder: ?line=BS_CASH
  useEffect(() => {
    const lineCode = searchParams.get('line')
    if (!lineCode || !report) return
    const line = report.lines.find((l) => l.line_code === lineCode)
    if (line?.drillable) void openDrill(line)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, searchParams])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && drawerOpen) {
        setDrawerOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  return (
    <div className={`report-workspace ${drawerOpen ? 'drawer-open' : ''}`}>
      <div className="page-header">
        <div>
          <h1>Statement</h1>
          <p>
            {entityCode ?? 'Entity'} · {label}. Click a line to drill — open the binder for the full
            WP document.
          </p>
        </div>
        <div className="toolbar">
          <button
            className="btn"
            onClick={() => void api.exportStatements(filters)}
            disabled={loading}
          >
            <Download size={14} /> Export pack
          </button>
          <button className="btn primary" onClick={() => void run()} disabled={loading}>
            {loading ? 'Running…' : 'Run report'}
          </button>
        </div>
      </div>

      <div className="filters">
        <select className="select" value={reportType} onChange={(e) => setReportType(e.target.value)}>
          <option value="income_statement">Income Statement</option>
          <option value="balance_sheet">Balance Sheet</option>
          <option value="cash_flow">Cash Flow</option>
        </select>
        <select className="select" value={reportPeriod} onChange={(e) => setReportPeriod(e.target.value)}>
          <option value="monthly">Monthly</option>
          <option value="quarterly">Quarterly</option>
          <option value="ytd">YTD</option>
          <option value="custom">Custom</option>
        </select>
        <select
          className="select"
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
        >
          {entities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.code} — {e.name}
            </option>
          ))}
        </select>
        <select className="select" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code}
            </option>
          ))}
        </select>
        <select className="select" value={compareScenarioId} onChange={(e) => setCompareScenarioId(e.target.value)}>
          <option value="">No scenario compare</option>
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              vs {s.code}
            </option>
          ))}
        </select>
        <label className="btn ghost">
          <input type="checkbox" checked={comparePrior} onChange={(e) => setComparePrior(e.target.checked)} />
          Prior period
        </label>
        <label className="btn ghost">
          <input type="checkbox" checked={compareYear} onChange={(e) => setCompareYear(e.target.checked)} />
          Prior year
        </label>
        <label className="btn ghost">
          <input type="checkbox" checked={compareBudget} onChange={(e) => setCompareBudget(e.target.checked)} />
          Budget
        </label>
      </div>

      {error && <div className="error">{error}</div>}

      <section className="panel statement-panel">
        <div className="panel-header">
          <h2>{report?.title ?? 'Report'}</h2>
          <span className="hint">
            {report ? `${report.currency} · ${new Date(report.generated_at).toLocaleString()}` : ''}
            {' · '}
            <span className="kbd">click line</span> to drill
          </span>
        </div>
        <div className="table-wrap statement-wrap">
          <table className="data statement-table">
            <thead>
              <tr>
                <th className="wp-col">Ref</th>
                <th>Line</th>
                <th className="num">Amount</th>
                {comparePrior && <th className="num">Prior</th>}
                {comparePrior && <th className="num">Var</th>}
                {compareYear && <th className="num">PY</th>}
                {compareBudget && <th className="num">Budget</th>}
                {compareScenarioId && <th className="num">Compare</th>}
                {compareScenarioId && <th className="num">Variance</th>}
              </tr>
            </thead>
            <tbody>
              {report?.lines.map((line) => {
                const active = activeLine === line.line_code && drawerOpen
                return (
                  <tr
                    key={line.line_code}
                    className={`${line.is_total ? 'total' : ''} ${line.drillable ? 'drillable' : ''} ${active ? 'wp-active' : ''}`}
                    onClick={() => void openDrill(line)}
                    title={line.drillable ? 'Open working paper' : undefined}
                  >
                    <td className="wp-col">{line.drillable ? line.wp_ref ?? '·' : ''}</td>
                    <td
                      style={{
                        paddingLeft: `${0.7 + line.indent_level * 1.1}rem`,
                        fontWeight: line.is_bold ? 700 : 400,
                      }}
                    >
                      {line.line_label}
                      {line.drillable && <span className="drill-cue">↗</span>}
                    </td>
                    <td className="num">{money(line.amount)}</td>
                    {comparePrior && (
                      <td className="num">
                        {line.prior_period_amount != null ? money(line.prior_period_amount) : '—'}
                      </td>
                    )}
                    {comparePrior && (
                      <td
                        className={`num ${line.flux_flag ? 'flux-cell' : ''}`}
                        title={line.flux_note ?? undefined}
                      >
                        {line.prior_period_variance != null ? money(line.prior_period_variance) : '—'}
                      </td>
                    )}
                    {compareYear && (
                      <td className="num">
                        {line.prior_year_amount != null ? money(line.prior_year_amount) : '—'}
                      </td>
                    )}
                    {compareBudget && (
                      <td className="num">
                        {line.budget_amount != null ? money(line.budget_amount) : '—'}
                      </td>
                    )}
                    {compareScenarioId && (
                      <td className="num">{line.compare_amount != null ? money(line.compare_amount) : '—'}</td>
                    )}
                    {compareScenarioId && (
                      <td className="num">{line.variance != null ? money(line.variance) : '—'}</td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      {report?.flux && report.flux.length > 0 && (
        <section className="panel flux-panel">
          <div className="panel-header">
            <h2>Analytical review</h2>
            <span className="hint">
              Material movements vs {report.prior_period_label ?? 'prior'} · click a line above to
              drill
            </span>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Line</th>
                  <th>Flag</th>
                  <th>Commentary</th>
                  <th className="num">Var</th>
                </tr>
              </thead>
              <tbody>
                {report.flux.slice(0, 12).map((item) => (
                  <tr key={`${item.line_code}-${item.flag}`}>
                    <td className="wp-col">{item.wp_ref ?? ''}</td>
                    <td>{item.line_label}</td>
                    <td>
                      <span className={`badge ${item.flag === 'material' ? 'open' : 'ok'}`}>
                        {item.flag}
                      </span>
                    </td>
                    <td className="hint">{item.note}</td>
                    <td className="num">{item.variance != null ? money(item.variance) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

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
