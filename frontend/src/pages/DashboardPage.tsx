import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Dashboard } from '../api'
import { money } from '../lib/format'

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .dashboard('CAD')
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <div className="error">{error}</div>
  if (!data) return <p className="hint">Loading dashboard…</p>

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p>Cash, earnings, reconciliations, and FX exposure at a glance.</p>
        </div>
        <div className="toolbar">
          <Link className="btn" to="/transactions?uncategorized_only=true">
            Review uncategorized
          </Link>
          <Link className="btn primary" to="/reconciliation">
            Open reconciliations
          </Link>
        </div>
      </div>

      <div className="kpi-grid">
        {data.kpis.map((kpi) => (
          <div key={kpi.key} className={`kpi ${kpi.status === 'warning' ? 'warn' : kpi.status === 'ok' ? 'ok' : ''}`}>
            <div className="kpi-label">{kpi.label}</div>
            <div className="kpi-value">
              {kpi.format === 'number' ? Number(kpi.value).toLocaleString() : money(kpi.value, kpi.currency)}
            </div>
          </div>
        ))}
      </div>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <h2>Cash by account</h2>
            <span className="hint">Reporting currency CAD</span>
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
                    <td>{row.name}</td>
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
    </div>
  )
}
