import { useEffect, useState } from 'react'
import { api, type Account, type Rule } from '../api'

export function SettingsPage() {
  const [rules, setRules] = useState<Rule[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [audit, setAudit] = useState<Array<Record<string, unknown>>>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.rules(), api.accounts(), api.auditLog()])
      .then(([r, a, log]) => {
        setRules(r)
        setAccounts(a)
        setAudit(log)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const accountLabel = (id: number) => {
    const a = accounts.find((x) => x.id === id)
    return a ? `${a.code} ${a.name}` : String(id)
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Categorization rules, chart of accounts, and audit trail.</p>
        </div>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <h2>Categorization rules</h2>
          </div>
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Priority</th>
                  <th>Name</th>
                  <th>Match</th>
                  <th>Assign</th>
                  <th className="num">Hits</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td>{r.priority}</td>
                    <td>{r.name}</td>
                    <td>{r.match_description_contains ?? '—'}</td>
                    <td>{accountLabel(r.assign_account_id)}</td>
                    <td className="num">{r.hit_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>Audit log</h2>
          </div>
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Who</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Field</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((row) => (
                  <tr key={String(row.id)}>
                    <td>{new Date(String(row.created_at)).toLocaleString()}</td>
                    <td>{String(row.actor ?? '—')}</td>
                    <td>{String(row.action)}</td>
                    <td>
                      {String(row.entity_table)} #{String(row.entity_id)}
                    </td>
                    <td>{String(row.field_name ?? '—')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="panel" style={{ marginTop: '0.85rem' }}>
        <div className="panel-header">
          <h2>Chart of accounts</h2>
        </div>
        <div className="table-wrap" style={{ maxHeight: 320 }}>
          <table className="data">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Type</th>
                <th>Statement</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id}>
                  <td>{a.code}</td>
                  <td>{a.name}</td>
                  <td>{a.account_type}</td>
                  <td>{a.statement}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
