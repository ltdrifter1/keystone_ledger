import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type BankAccount, type Reconciliation, type ReconWorkspace } from '../api'
import { useToast } from '../hooks/useToast'
import { money } from '../lib/format'

export function ReconciliationPage() {
  const [banks, setBanks] = useState<BankAccount[]>([])
  const [recons, setRecons] = useState<Reconciliation[]>([])
  const [workspace, setWorkspace] = useState<ReconWorkspace | null>(null)
  const [bankId, setBankId] = useState('')
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [month, setMonth] = useState(String(new Date().getMonth() + 1))
  const [ending, setEnding] = useState('')
  const [showUnclearedOnly, setShowUnclearedOnly] = useState(false)
  const [showUncategorizedOnly, setShowUncategorizedOnly] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { toast, show } = useToast()

  const refreshList = async () => {
    const [b, r] = await Promise.all([api.bankAccounts(), api.reconciliations()])
    setBanks(b)
    setRecons(r)
  }

  useEffect(() => {
    refreshList().catch((e: Error) => setError(e.message))
  }, [])

  const openWorkspace = async (id: number) => {
    setError(null)
    const ws = await api.reconWorkspace(id)
    setWorkspace(ws)
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
      setEnding('')
      await refreshList()
      await openWorkspace(recon.id)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const toggleClear = async (transactionId: number, isCleared: boolean) => {
    if (!workspace || workspace.status === 'locked') return
    try {
      await api.clearReconItems(workspace.id, [transactionId], !isCleared)
      await openWorkspace(workspace.id)
      await refreshList()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const clearAllCategorized = async () => {
    if (!workspace) return
    try {
      const ws = await api.clearAllRecon(workspace.id, true)
      setWorkspace(ws)
      show('Cleared all categorized items')
      await refreshList()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const sync = async () => {
    if (!workspace) return
    try {
      const ws = await api.syncRecon(workspace.id)
      setWorkspace(ws)
      show(`Synced${ws.added ? ` · +${ws.added} items` : ''}`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const complete = async () => {
    if (!workspace) return
    try {
      await api.completeRecon(workspace.id)
      show('Period locked')
      await openWorkspace(workspace.id)
      await refreshList()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const bankName = (id: number) => banks.find((b) => b.id === id)?.name ?? `#${id}`

  const visibleItems = useMemo(() => {
    if (!workspace) return []
    return workspace.items.filter((it) => {
      if (showUnclearedOnly && it.is_cleared) return false
      if (showUncategorizedOnly && !(it.status === 'uncategorized' && !it.is_split)) return false
      return true
    })
  }, [workspace, showUnclearedOnly, showUncategorizedOnly])

  const diffZero = workspace ? Math.abs(workspace.difference) < 0.0001 : false

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Reconciliation</h1>
          <p>Beginning balance → clear items → statement ending balance → lock period.</p>
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
              <input
                className="input"
                type="number"
                min={1}
                max={12}
                value={month}
                onChange={(e) => setMonth(e.target.value)}
              />
            </div>
            <input
              className="input"
              type="number"
              step="0.01"
              placeholder="Statement ending balance"
              value={ending}
              onChange={(e) => setEnding(e.target.value)}
            />
            <button className="btn primary" disabled={!bankId || ending === ''} onClick={() => void create()}>
              Create reconciliation
            </button>
            <p className="hint">Prior open periods for the same account must be locked first.</p>
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
                    className={workspace?.id === r.id ? 'selected' : ''}
                    onClick={() => void openWorkspace(r.id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      {r.period_year}-{String(r.period_month).padStart(2, '0')}
                    </td>
                    <td>{bankName(r.bank_account_id)}</td>
                    <td>
                      <span className={`badge ${r.status === 'locked' ? 'ok' : 'open'}`}>{r.status}</span>
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
            <h2>
              {workspace
                ? `Tie-out · ${workspace.period_year}-${String(workspace.period_month).padStart(2, '0')} · ${bankName(workspace.bank_account_id)}`
                : 'Workspace'}
            </h2>
            {workspace && workspace.status !== 'locked' && (
              <div className="toolbar">
                <button className="btn" onClick={() => void sync()}>
                  Sync items
                </button>
                <button className="btn" onClick={() => void clearAllCategorized()}>
                  Clear categorized
                </button>
                <button className="btn primary" disabled={!workspace.can_lock} onClick={() => void complete()}>
                  Complete & lock
                </button>
              </div>
            )}
          </div>

          {!workspace && (
            <p className="hint" style={{ padding: '1rem' }}>
              Select or create a reconciliation period.
            </p>
          )}

          {workspace && (
            <>
              <div className="tie-strip">
                <div className="kpi">
                  <div className="kpi-label">Beginning</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {money(workspace.beginning_balance)}
                  </div>
                </div>
                <div className="tie-op">+</div>
                <div className="kpi">
                  <div className="kpi-label">Cleared</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {money(workspace.cleared_total)}
                  </div>
                </div>
                <div className="tie-op">=</div>
                <div className="kpi">
                  <div className="kpi-label">Book (cleared)</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {money(workspace.calculated_balance)}
                  </div>
                </div>
                <div className="tie-op">vs</div>
                <div className="kpi">
                  <div className="kpi-label">Statement</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {money(workspace.statement_ending_balance)}
                  </div>
                </div>
                <div className={`kpi ${diffZero ? 'ok' : 'warn'}`}>
                  <div className="kpi-label">Difference</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {money(workspace.difference)}
                  </div>
                </div>
              </div>

              <div className="filters" style={{ padding: '0 0.85rem' }}>
                <label className="btn ghost">
                  <input
                    type="checkbox"
                    checked={showUnclearedOnly}
                    onChange={(e) => setShowUnclearedOnly(e.target.checked)}
                  />
                  Uncleared only
                </label>
                <label className="btn ghost">
                  <input
                    type="checkbox"
                    checked={showUncategorizedOnly}
                    onChange={(e) => setShowUncategorizedOnly(e.target.checked)}
                  />
                  Uncategorized
                </label>
                {workspace.uncategorized_cleared_count > 0 && (
                  <Link
                    className="btn"
                    to={`/transactions?bank_account_id=${workspace.bank_account_id}&uncategorized_only=true`}
                  >
                    Categorize {workspace.uncategorized_cleared_count} cleared
                  </Link>
                )}
                {workspace.status === 'locked' && (
                  <span className="badge ok">
                    Locked {workspace.locked_at ? new Date(workspace.locked_at).toLocaleString() : ''} by{' '}
                    {workspace.locked_by ?? 'controller'}
                  </span>
                )}
              </div>

              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Clr</th>
                      <th>Date</th>
                      <th>Description</th>
                      <th>Account</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleItems.map((it) => (
                      <tr key={it.id} className={!it.in_period ? 'prior-item' : ''}>
                        <td>
                          <input
                            type="checkbox"
                            checked={it.is_cleared}
                            disabled={workspace.status === 'locked'}
                            onChange={() => void toggleClear(it.transaction_id, it.is_cleared)}
                          />
                        </td>
                        <td>
                          {it.txn_date}
                          {!it.in_period && <span className="badge">PRIOR</span>}
                        </td>
                        <td>{it.description}</td>
                        <td>
                          {it.is_split
                            ? 'Split'
                            : it.account_code
                              ? `${it.account_code} ${it.account_name}`
                              : <span className="badge open">uncategorized</span>}
                        </td>
                        <td className="num">{money(it.amount, it.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="hint" style={{ padding: '0.75rem 1rem' }}>
                Uncleared {workspace.uncleared_count} ({money(workspace.uncleared_total)}) carry to next period.
                Difference must be zero and cleared items categorized before lock.
              </p>
            </>
          )}
        </section>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
