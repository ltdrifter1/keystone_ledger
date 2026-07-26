import { useEffect, useState } from 'react'
import { api, type Entity, type Report, type Scenario } from '../api'
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

  useEffect(() => {
    Promise.all([api.entities(), api.scenarios()]).then(([e, s]) => {
      setEntities(e)
      setScenarios(s)
    })
  }, [])

  const run = async () => {
    setLoading(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
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
      }
      const res = await api.report(body)
      setReport(res)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p>Filter-driven statements from categorized transactions (FACT + dimensions).</p>
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

      <section className="panel">
        <div className="panel-header">
          <h2>{report?.title ?? 'Report'}</h2>
          <span className="hint">{report ? `${report.currency} · ${new Date(report.generated_at).toLocaleString()}` : ''}</span>
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Line</th>
                <th className="num">Amount</th>
                {compareScenarioId && <th className="num">Compare</th>}
                {compareScenarioId && <th className="num">Variance</th>}
              </tr>
            </thead>
            <tbody>
              {report?.lines.map((line) => (
                <tr key={line.line_code} className={line.is_total ? 'total' : ''}>
                  <td style={{ paddingLeft: `${0.7 + line.indent_level * 1.1}rem`, fontWeight: line.is_bold ? 700 : 400 }}>
                    {line.line_label}
                  </td>
                  <td className="num">{money(line.amount)}</td>
                  {compareScenarioId && <td className="num">{line.compare_amount != null ? money(line.compare_amount) : '—'}</td>}
                  {compareScenarioId && <td className="num">{line.variance != null ? money(line.variance) : '—'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
