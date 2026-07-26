import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type DrillOut, type Entity, type Report, type ReportFilters, type ReportLine, type Scenario } from '../api'
import { WorkingPaperDrawer } from '../components/WorkingPaperDrawer'
import { money } from '../lib/format'

export function ReportsPage() {
  const [reportType, setReportType] = useState('income_statement')
  const [period, setPeriod] = useState('ytd')
  const [entityId, setEntityId] = useState('')
  const [scenarioId, setScenarioId] = useState('1')
  const [compareScenarioId, setCompareScenarioId] = useState('')
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

  const filters: ReportFilters = useMemo(
    () => ({
      report_type: reportType,
      period,
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      scenario_id: Number(scenarioId),
      reporting_currency: 'CAD',
      consolidate: !entityId,
      entity_ids: entityId ? [Number(entityId)] : null,
      compare_scenario_id: compareScenarioId ? Number(compareScenarioId) : null,
      as_of_date: new Date().toISOString().slice(0, 10),
    }),
    [reportType, period, scenarioId, entityId, compareScenarioId],
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
          <h1>Reports</h1>
          <p>Click any line to open the CaseWare-style working paper — detail that ties to the statement.</p>
        </div>
        <div className="toolbar">
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
        <select className="select" value={period} onChange={(e) => setPeriod(e.target.value)}>
          <option value="monthly">Monthly</option>
          <option value="quarterly">Quarterly</option>
          <option value="ytd">YTD</option>
          <option value="custom">Custom</option>
        </select>
        <select className="select" value={entityId} onChange={(e) => setEntityId(e.target.value)}>
          <option value="">Consolidated</option>
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
          <option value="">No comparison</option>
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              vs {s.code}
            </option>
          ))}
        </select>
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
