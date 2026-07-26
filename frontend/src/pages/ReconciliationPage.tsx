import { useEffect, useState } from 'react'
import { api, type BankAccount, type Reconciliation } from '../api'
import { useToast } from '../hooks/useToast'
import { money } from '../lib/format'

type Item = {
  id: number
  transaction_id: number
  is_cleared: boolean
  txn_date: string
  description: string
  amount: number
  currency: string
}

export function ReconciliationPage() {
  const [banks, setBanks] = useState<BankAccount[]>([])
  const [recons, setRecons] = useState<Reconciliation[]>([])
  const [active, setActive] = useState<Reconciliation | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [bankId, setBankId] = useState('')
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [month, setMonth] = useState(String(new Date().getMonth() + 1))
  const [ending, setEnding] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { toast, show } = useToast()

  const refresh = async () => {
    const [b, r] = await Promise.all([api.bankAccounts(), api.reconciliations()])
    setBanks(b)
    setRecons(r)
  }

  useEffect(() => {
    refresh().catch((e: Error) => setError(e.message))
  }, [])

  const openRecon = async (recon: Reconciliation) => {
    setActive(recon)
    const list = await api.reconItems(recon.id)
    setItems(list)
  }

  const create = async () => {
    try {
      const recon = await api.createReconciliation({
        bank_account_id: Number(bankId),
        period_year: Number(year),
        period_month: Number(month),
        statement_ending_balance: Number(ending),
      })
      show('Reconciliation created')
      await refresh()
      await openRecon(recon)
      setEnding('')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const toggleClear = async (transactionId: number, isCleared: boolean) => {
    if (!active) return
    const updated = await api.clearReconItems(active.id, [transactionId], !isCleared)
    setActive(updated)
    setItems((prev) =>
      prev.map((it) => (it.transaction_id === transactionId ? { ...it, is_cleared: !isCleared } : it)),
    )
    await refresh()
  }

  const complete = async () => {
    if (!active) return
    try {
      const updated = await api.completeRecon(active.id)
      setActive(updated)
      show('Reconciliation completed & locked')
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const bankName = (id: number) => banks.find((b) => b.id === id)?.name ?? `#${id}`

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Reconciliation</h1>
          <p>Monthly bank reconciliations with cleared items, differences, and period locks.</p>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <h2>Start period</h2>
          </div>
          <div style={{ padding: '1rem', display: 'grid', gap: '0.65rem' }}>
            <select className="select" value={bankId} onChange={(e) => setBankId(e.target.value)}>
              <option value="">Bank account…</option>
              {banks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.currency})
                </option>
              ))}
            </select>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
              <input className="input" type="number" value={year} onChange={(e) => setYear(e.target.value)} />
              <input className="input" type="number" min={1} max={12} value={month} onChange={(e) => setMonth(e.target.value)} />
            </div>
            <input
              className="input"
              type="number"
              step="0.01"
              placeholder="Statement ending balance"
              value={ending}
              onChange={(e) => setEnding(e.target.value)}
            />
            <button className="btn primary" disabled={!bankId || !ending} onClick={() => void create()}>
              Create reconciliation
            </button>
          </div>

          <div className="panel-header">
            <h2>Periods</h2>
          </div>
          <div className="table-wrap" style={{ maxHeight: 360 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Account</th>
                  <th>Status</th>
                  <th className="num">Diff</th>
                </tr>
              </thead>
              <tbody>
                {recons.map((r) => (
                  <tr
                    key={r.id}
                    className={active?.id === r.id ? 'selected' : ''}
                    onClick={() => void openRecon(r)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      {r.period_year}-{String(r.period_month).padStart(2, '0')}
                    </td>
                    <td>{bankName(r.bank_account_id)}</td>
                    <td>
                      <span className={`badge ${r.status === 'locked' || r.status === 'completed' ? 'ok' : 'open'}`}>
                        {r.status}
                      </span>
                    </td>
                    <td className="num">{money(r.difference ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>{active ? `Workspace · ${active.period_year}-${String(active.period_month).padStart(2, '0')}` : 'Workspace'}</h2>
            {active && (
              <button className="btn primary" onClick={() => void complete()} disabled={active.status === 'locked'}>
                Complete & lock
              </button>
            )}
          </div>
          {!active && <p className="hint" style={{ padding: '1rem' }}>Select or create a reconciliation period.</p>}
          {active && (
            <>
              <div className="kpi-grid" style={{ padding: '0.85rem', marginBottom: 0, gridTemplateColumns: 'repeat(3, 1fr)' }}>
                <div className="kpi">
                  <div className="kpi-label">Statement</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>{money(active.statement_ending_balance)}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Cleared book</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>{money(active.calculated_balance ?? 0)}</div>
                </div>
                <div className={`kpi ${Number(active.difference) === 0 ? 'ok' : 'warn'}`}>
                  <div className="kpi-label">Difference</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>{money(active.difference ?? 0)}</div>
                </div>
              </div>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Cleared</th>
                      <th>Date</th>
                      <th>Description</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it) => (
                      <tr key={it.id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={it.is_cleared}
                            disabled={active.status === 'locked'}
                            onChange={() => void toggleClear(it.transaction_id, it.is_cleared)}
                          />
                        </td>
                        <td>{it.txn_date}</td>
                        <td>{it.description}</td>
                        <td className="num">{money(it.amount, it.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="hint" style={{ padding: '0.75rem 1rem' }}>
                Uncleared {active.uncleared_count} · Cleared {active.cleared_count}. Difference must be zero to lock.
              </p>
            </>
          )}
        </section>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
