import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type BankAccount, type Entity } from '../api'
import { money } from '../lib/format'

export function BankAccountsPage() {
  const [banks, setBanks] = useState<BankAccount[]>([])
  const [entities, setEntities] = useState<Entity[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.bankAccounts(), api.entities()])
      .then(([b, e]) => {
        setBanks(b)
        setEntities(e)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const entityCode = (id: number) => entities.find((e) => e.id === id)?.code ?? String(id)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Bank Accounts</h1>
          <p>Attributes of transactions — not the center of the model.</p>
        </div>
        <Link className="btn primary" to="/transactions">
          View transactions
        </Link>
      </div>
      {error && <div className="error">{error}</div>}
      <section className="panel">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Name</th>
                <th>Entity</th>
                <th>Institution</th>
                <th>Number</th>
                <th>Currency</th>
                <th className="num">Opening</th>
                <th className="num">Budget</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {banks.map((b) => (
                <tr key={b.id}>
                  <td>{b.name}</td>
                  <td>
                    <span className="badge">{entityCode(b.entity_id)}</span>
                  </td>
                  <td>{b.institution ?? '—'}</td>
                  <td>{b.account_number}</td>
                  <td>{b.currency}</td>
                  <td className="num">{money(b.opening_balance, b.currency)}</td>
                  <td className="num">
                    {b.budget_balance == null || b.budget_balance === ''
                      ? '—'
                      : money(b.budget_balance, b.currency)}
                  </td>
                  <td>
                    <Link className="btn ghost" to={`/transactions?bank_account_id=${b.id}`}>
                      Transactions
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
