import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CheckCircle2,
  Upload,
  RefreshCw,
  Lock,
  AlertTriangle,
  Sparkles,
} from 'lucide-react'
import {
  api,
  type Account,
  type BankAccount,
  type CloseException,
  type ClosePackStatus,
  type MonthCloseOverview,
} from '../api'
import { useToast } from '../hooks/useToast'
import { money } from '../lib/format'

export function ClosePackPage() {
  const now = new Date()
  const [year, setYear] = useState(String(now.getFullYear()))
  const [month, setMonth] = useState(String(now.getMonth() + 1))
  const [banks, setBanks] = useState<BankAccount[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [overview, setOverview] = useState<MonthCloseOverview | null>(null)
  const [active, setActive] = useState<ClosePackStatus | null>(null)
  const [bankId, setBankId] = useState('')
  const [ending, setEnding] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rememberRule, setRememberRule] = useState(true)
  const { toast, show } = useToast()

  const loadOverview = useCallback(async () => {
    const data = await api.closeMonthOverview(Number(year), Number(month))
    setOverview(data)
    return data
  }, [year, month])

  useEffect(() => {
    Promise.all([api.bankAccounts(), api.accounts()])
      .then(([b, a]) => {
        setBanks(b)
        setAccounts(a)
        if (b[0]) setBankId(String(b[0].id))
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    loadOverview().catch((e: Error) => setError(e.message))
  }, [loadOverview])

  const runPack = async () => {
    if (!bankId || ending === '') {
      show('Choose a bank and statement ending balance')
      return
    }
    setRunning(true)
    setError(null)
    try {
      const result = await api.runClosePack({
        bankAccountId: Number(bankId),
        periodYear: Number(year),
        periodMonth: Number(month),
        statementEndingBalance: Number(ending),
        file,
      })
      setActive(result)
      setFile(null)
      await loadOverview()
      if (result.can_lock) {
        show(`Close pack ready — ${result.auto_cleared ?? 0} auto-cleared · lock when ready`)
      } else {
        show(
          `Close pack ran — ${result.blocking_count} blocking exception${result.blocking_count === 1 ? '' : 's'}`,
        )
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  const openPack = async (pack: ClosePackStatus) => {
    setBankId(String(pack.bank_account_id))
    if (pack.statement_ending_balance != null) {
      setEnding(String(pack.statement_ending_balance))
    }
    if (!pack.reconciliation_id) {
      setActive(pack)
      return
    }
    try {
      const fresh = await api.getClosePack(pack.reconciliation_id)
      setActive(fresh)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const refreshActive = async () => {
    if (!active?.reconciliation_id) return
    const fresh = await api.refreshClosePack(active.reconciliation_id)
    setActive(fresh)
    await loadOverview()
    show('Rules re-applied · auto-clear refreshed')
  }

  const categorize = async (ex: CloseException, accountId: number) => {
    if (!active?.reconciliation_id) return
    try {
      const fresh = await api.closeCategorizeException(active.reconciliation_id, ex.transaction_id, {
        account_id: accountId,
        create_rule: rememberRule,
        clear_after: true,
      })
      setActive(fresh)
      await loadOverview()
      show(rememberRule ? 'Categorized + cleared · rule remembered' : 'Categorized + cleared')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const clearItem = async (ex: CloseException, isCleared = true) => {
    if (!active?.reconciliation_id) return
    const fresh = await api.closeClearException(active.reconciliation_id, ex.transaction_id, isCleared)
    setActive(fresh)
    await loadOverview()
  }

  const voidDup = async (ex: CloseException) => {
    if (!active?.reconciliation_id) return
    const fresh = await api.closeVoidDuplicate(active.reconciliation_id, ex.transaction_id)
    setActive(fresh)
    await loadOverview()
    show('Duplicate voided')
  }

  const lockActive = async () => {
    if (!active?.reconciliation_id) return
    try {
      const fresh = await api.lockClosePack(active.reconciliation_id)
      setActive(fresh)
      await loadOverview()
      show('Period locked')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const lockMonthAll = async () => {
    try {
      const data = await api.lockMonth(Number(year), Number(month))
      setOverview(data)
      if (active?.reconciliation_id) {
        const match = data.packs.find((p) => p.reconciliation_id === active.reconciliation_id)
        if (match) setActive(match)
      }
      show(`Locked ${data.newly_locked.length} bank(s)`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const exceptionsByKind = useMemo(() => {
    const map = new Map<string, CloseException[]>()
    for (const ex of active?.exceptions ?? []) {
      const list = map.get(ex.kind) ?? []
      list.push(ex)
      map.set(ex.kind, list)
    }
    return map
  }, [active])

  const kindLabel: Record<string, string> = {
    uncategorized: 'Uncategorized',
    duplicate: 'Duplicates',
    difference: 'Difference drivers',
    intercompany: 'Intercompany',
    uncleared: 'Uncleared',
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Statement Close Pack</h1>
          <p>Upload statement → auto-clear → resolve exceptions → lock. Month-end as an exception pass.</p>
        </div>
        <div className="toolbar">
          <button
            className="btn primary"
            disabled={!overview?.can_lock_month}
            onClick={() => void lockMonthAll()}
          >
            <Lock size={14} /> Lock month
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="filters">
        <input className="input" type="number" value={year} onChange={(e) => setYear(e.target.value)} />
        <input
          className="input"
          type="number"
          min={1}
          max={12}
          value={month}
          onChange={(e) => setMonth(e.target.value)}
        />
        {overview && (
          <span className="badge ok">
            {overview.banks_locked}/{overview.banks_total} locked · {overview.banks_ready_to_lock} ready
          </span>
        )}
        {overview?.all_locked && (
          <span className="badge ok">
            <CheckCircle2 size={12} /> Month complete
          </span>
        )}
      </div>

      <div className="close-pack-layout">
        <section className="panel">
          <div className="panel-header">
            <h2>
              <Sparkles size={14} /> Run pack
            </h2>
          </div>
          <div className="close-run-form">
            <select className="select" value={bankId} onChange={(e) => setBankId(e.target.value)}>
              {banks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.currency})
                </option>
              ))}
            </select>
            <input
              className="input"
              type="number"
              step="0.01"
              placeholder="Statement ending balance"
              value={ending}
              onChange={(e) => setEnding(e.target.value)}
            />
            <label className="btn">
              <Upload size={14} />
              {file ? file.name : 'Statement CSV/Excel (optional)'}
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                hidden
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <button className="btn primary" disabled={running} onClick={() => void runPack()}>
              {running ? 'Running…' : 'Run close pack'}
            </button>
            <p className="hint">
              Imports (optional), applies rules, opens the recon, auto-clears categorized in-period items, then shows
              only exceptions.
            </p>
          </div>

          <div className="panel-header">
            <h2>Banks · {overview?.period_label}</h2>
          </div>
          <div className="table-wrap" style={{ maxHeight: 360 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Bank</th>
                  <th>Entity</th>
                  <th>Status</th>
                  <th className="num">Diff</th>
                  <th className="num">Exc</th>
                </tr>
              </thead>
              <tbody>
                {overview?.packs.map((p) => (
                  <tr
                    key={p.bank_account_id}
                    className={active?.bank_account_id === p.bank_account_id ? 'selected' : ''}
                    style={{ cursor: 'pointer' }}
                    onClick={() => void openPack(p)}
                  >
                    <td>{p.bank_account_name}</td>
                    <td>
                      <span className="badge">{p.entity_code}</span>
                    </td>
                    <td>
                      <span
                        className={`badge ${p.is_locked ? 'ok' : p.can_lock ? 'ok' : p.status === 'not_started' ? '' : 'open'}`}
                      >
                        {p.is_locked ? 'locked' : p.can_lock ? 'ready' : p.status}
                      </span>
                    </td>
                    <td className="num">{p.difference == null ? '—' : money(p.difference)}</td>
                    <td className="num">{p.blocking_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel close-exceptions-panel">
          <div className="panel-header">
            <h2>
              {active
                ? `${active.bank_account_name ?? 'Bank'} · ${active.period_label}`
                : 'Exceptions'}
            </h2>
            {active?.reconciliation_id && active.status !== 'locked' && (
              <div className="toolbar">
                <button className="btn" onClick={() => void refreshActive()}>
                  <RefreshCw size={14} /> Refresh
                </button>
                <button className="btn primary" disabled={!active.can_lock} onClick={() => void lockActive()}>
                  <Lock size={14} /> Complete & lock
                </button>
              </div>
            )}
          </div>

          {!active && (
            <p className="hint" style={{ padding: '1rem' }}>
              Run a close pack or select a bank to work exceptions.
            </p>
          )}

          {active && (
            <>
              <div className="tie-strip close-tie">
                <div className="kpi">
                  <div className="kpi-label">Beginning</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {money(active.beginning_balance)}
                  </div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Statement</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {active.statement_ending_balance == null
                      ? '—'
                      : money(active.statement_ending_balance)}
                  </div>
                </div>
                <div className={`kpi ${active.difference === 0 ? 'ok' : 'warn'}`}>
                  <div className="kpi-label">Difference</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {active.difference == null ? '—' : money(active.difference)}
                  </div>
                </div>
                <div className={`kpi ${active.blocking_count === 0 ? 'ok' : 'warn'}`}>
                  <div className="kpi-label">Blocking</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {active.blocking_count}
                  </div>
                </div>
              </div>

              {active.is_locked && (
                <div className="close-locked-banner">
                  <CheckCircle2 size={16} /> Locked
                  {active.locked_at ? ` · ${new Date(active.locked_at).toLocaleString()}` : ''}
                </div>
              )}

              {active.can_lock && !active.is_locked && (
                <div className="close-ready-banner">
                  <CheckCircle2 size={16} /> Ready to lock — no blocking exceptions, difference is zero.
                </div>
              )}

              {!active.reconciliation_id && (
                <p className="hint" style={{ padding: '0 1rem 1rem' }}>
                  Not started. Enter the statement ending balance and run the close pack.
                </p>
              )}

              {active.reconciliation_id && active.exception_count === 0 && !active.is_locked && (
                <p className="hint" style={{ padding: '0 1rem 1rem' }}>
                  No exceptions. Cleared {active.cleared_count} · Uncleared {active.uncleared_count} (timing).
                </p>
              )}

              {active.exception_count > 0 && (
                <div className="exception-stack">
                  <label className="btn ghost" style={{ margin: '0 1rem' }}>
                    <input
                      type="checkbox"
                      checked={rememberRule}
                      onChange={(e) => setRememberRule(e.target.checked)}
                    />
                    Remember rules on categorize
                  </label>

                  {[...exceptionsByKind.entries()].map(([kind, rows]) => (
                    <div key={kind} className="exception-group">
                      <div className="exception-group-head">
                        <AlertTriangle size={14} />
                        {kindLabel[kind] ?? kind}
                        <span className="badge">{rows.length}</span>
                      </div>
                      <div className="table-wrap">
                        <table className="data">
                          <thead>
                            <tr>
                              <th>Date</th>
                              <th>Description</th>
                              <th className="num">Amount</th>
                              <th>Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {rows.map((ex) => (
                              <tr key={`${ex.kind}-${ex.transaction_id}`}>
                                <td>
                                  {ex.txn_date}
                                  {!ex.in_period && <span className="badge">PRIOR</span>}
                                  {ex.blocking && <span className="badge open">BLOCK</span>}
                                </td>
                                <td className="desc-cell">
                                  <div>{ex.description}</div>
                                  <div className="hint">{ex.message}</div>
                                </td>
                                <td className="num">{money(ex.amount, ex.currency)}</td>
                                <td onClick={(e) => e.stopPropagation()}>
                                  {kind === 'uncategorized' && !active.is_locked && (
                                    <select
                                      className="select inline"
                                      defaultValue=""
                                      onChange={(e) => {
                                        if (e.target.value) void categorize(ex, Number(e.target.value))
                                        e.target.value = ''
                                      }}
                                    >
                                      <option value="">Categorize…</option>
                                      {accounts.map((a) => (
                                        <option key={a.id} value={a.id}>
                                          {a.code} {a.name}
                                        </option>
                                      ))}
                                    </select>
                                  )}
                                  {kind === 'duplicate' && !active.is_locked && (
                                    <div className="toolbar">
                                      <button className="btn ghost" onClick={() => void voidDup(ex)}>
                                        Void dup
                                      </button>
                                      <button className="btn ghost" onClick={() => void clearItem(ex, true)}>
                                        Keep & clear
                                      </button>
                                    </div>
                                  )}
                                  {(kind === 'difference' || kind === 'uncleared') && !active.is_locked && (
                                    <button className="btn ghost" onClick={() => void clearItem(ex, true)}>
                                      Clear
                                    </button>
                                  )}
                                  {kind === 'intercompany' && (
                                    <button
                                      className="btn ghost"
                                      onClick={() =>
                                        void api.autoMatchIc().then(async () => {
                                          await refreshActive()
                                          show('IC match attempted')
                                        })
                                      }
                                    >
                                      Match IC
                                    </button>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
