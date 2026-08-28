import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  api,
  type Account,
  type BankAccount,
  type Department,
  type Entity,
  type Transaction,
} from '../api'
import { AccountPicker } from '../components/AccountPicker'
import { useToast } from '../hooks/useToast'
import { money } from '../lib/format'

type DraftSplit = { account_id: string; amount: string; memo: string }

export function TransactionsPage() {
  const [params, setParams] = useSearchParams()
  const [rows, setRows] = useState<Transaction[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [entities, setEntities] = useState<Entity[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [banks, setBanks] = useState<BankAccount[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [activeId, setActiveId] = useState<number | null>(null)
  const [search, setSearch] = useState(params.get('search') ?? '')
  const [entityId, setEntityId] = useState(params.get('entity_id') ?? '')
  const [bankId, setBankId] = useState(params.get('bank_account_id') ?? '')
  const [uncategorizedOnly, setUncategorizedOnly] = useState(params.get('uncategorized_only') === 'true')
  const [duplicatesOnly, setDuplicatesOnly] = useState(false)
  const [unreconciledOnly, setUnreconciledOnly] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [rememberRule, setRememberRule] = useState(true)
  const [splitForId, setSplitForId] = useState<number | null>(null)
  const [splitDrafts, setSplitDrafts] = useState<DraftSplit[]>([])
  const searchRef = useRef<HTMLInputElement>(null)
  const { toast, show } = useToast()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.transactions({
        search: search || undefined,
        entity_id: entityId || undefined,
        bank_account_id: bankId || undefined,
        uncategorized_only: uncategorizedOnly || undefined,
        duplicates_only: duplicatesOnly || undefined,
        unreconciled_only: unreconciledOnly || undefined,
        limit: 500,
      })
      setRows(data)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [search, entityId, bankId, uncategorizedOnly, duplicatesOnly, unreconciledOnly])

  useEffect(() => {
    Promise.all([api.accounts(), api.entities(), api.bankAccounts(), api.departments()]).then(
      ([a, e, b, d]) => {
        setAccounts(a)
        setEntities(e)
        setBanks(b)
        setDepartments(d)
      },
    )
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const next = new URLSearchParams()
    if (search) next.set('search', search)
    if (entityId) next.set('entity_id', entityId)
    if (bankId) next.set('bank_account_id', bankId)
    if (uncategorizedOnly) next.set('uncategorized_only', 'true')
    setParams(next, { replace: true })
  }, [search, entityId, bankId, uncategorizedOnly, setParams])

  const active = useMemo(() => rows.find((r) => r.id === activeId) ?? null, [rows, activeId])

  const patchRow = (updated: Transaction) => {
    setRows((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
  }

  const inlineCategorize = async (txn: Transaction, accountId: number) => {
    if (!txn.is_editable && txn.is_period_locked) {
      show('Period locked — cannot edit')
      return
    }
    try {
      const updated = await api.categorize(txn.id, {
        account_id: accountId,
        create_rule: rememberRule,
      })
      patchRow(updated)
      show(rememberRule ? `Categorized + rule saved` : `Categorized #${txn.id}`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const inlineDept = async (txn: Transaction, departmentId: number | null) => {
    try {
      const updated = await api.updateTransaction(txn.id, { department_id: departmentId })
      patchRow(updated)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const inlineCounterEntity = async (txn: Transaction, counterEntityId: number | null) => {
    try {
      const updated = await api.updateTransaction(txn.id, { counter_entity_id: counterEntityId })
      patchRow(updated)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const openSplit = (txn: Transaction) => {
    if (txn.is_period_locked || txn.is_reconciled) {
      show('Locked/reconciled transactions cannot be split')
      return
    }
    setActiveId(txn.id)
    setSplitForId(txn.id)
    if (txn.splits && txn.splits.length > 0) {
      setSplitDrafts(
        txn.splits.map((s) => ({
          account_id: String(s.account_id),
          amount: String(s.amount),
          memo: s.memo ?? '',
        })),
      )
    } else {
      const half = (Number(txn.amount) / 2).toFixed(2)
      const rest = (Number(txn.amount) - Number(half)).toFixed(2)
      setSplitDrafts([
        { account_id: txn.account_id ? String(txn.account_id) : '', amount: half, memo: '' },
        { account_id: '', amount: rest, memo: '' },
      ])
    }
  }

  const saveSplit = async () => {
    if (!splitForId) return
    const splits = splitDrafts.map((d, i) => ({
      account_id: Number(d.account_id),
      amount: Number(d.amount),
      memo: d.memo || undefined,
      sort_order: i,
    }))
    if (splits.some((s) => !s.account_id || Number.isNaN(s.amount))) {
      setError('Each split needs an account and amount')
      return
    }
    try {
      const updated = await api.splitTransaction(splitForId, splits)
      patchRow(updated)
      setSplitForId(null)
      show('Split saved')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const bulkCategorizeSelected = async (accountId: number) => {
    const ids = [...selected]
    if (!ids.length) return
    try {
      const res = await api.bulkCategorize(ids, accountId, rememberRule)
      show(`Categorized ${res.categorized}${res.skipped_locked ? ` · skipped locked ${res.skipped_locked}` : ''}`)
      setSelected(new Set())
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const toggle = (id: number, additive: boolean) => {
    setActiveId(id)
    setSelected((prev) => {
      const next = new Set(additive ? prev : [])
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
        if (e.key === 'Escape') (e.target as HTMLElement).blur()
        return
      }
      if (e.key === '/') {
        e.preventDefault()
        searchRef.current?.focus()
      }
      if (e.key.toLowerCase() === 'r') {
        e.preventDefault()
        void api.applyRules().then(async (res) => {
          show(`Rules categorized ${res.categorized}`)
          await load()
        })
      }
      if (e.key.toLowerCase() === 'i') {
        e.preventDefault()
        void api.autoMatchIc().then(async (res) => {
          show(`Matched ${res.matched} intercompany pair(s)`)
          await load()
        })
      }
      if (e.key.toLowerCase() === 's' && active) {
        e.preventDefault()
        openSplit(active)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, load])

  const onImport = async (file: File | null) => {
    if (!file) return
    if (!bankId) {
      show('Choose a bank account filter before importing')
      return
    }
    try {
      const res = await api.importBank(Number(bankId), file)
      show(`Imported ${res.imported} · dupes ${res.duplicates_flagged} · auto ${res.auto_categorized}`)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const onImportSynoptic = async (file: File | null) => {
    if (!file) return
    if (!bankId) {
      show('Choose the entity bank (e.g. CAN 1010) before importing a synoptic')
      return
    }
    try {
      const res = await api.importSynoptic(Number(bankId), file)
      const errHint = res.errors?.length ? ` · ${res.errors.length} warnings` : ''
      show(
        `Synoptic: ${res.imported} imported · ${res.auto_categorized} mapped · ${res.skipped} skipped${errHint}`,
      )
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const onImportAdjPack = async (file: File | null) => {
    if (!file) return
    try {
      const res = await api.importAdjPack(file, entityId ? Number(entityId) : undefined)
      const errHint = res.errors?.length ? ` · ${res.errors.length} warnings` : ''
      show(
        `Adj pack: ${res.imported} journals · ${res.skipped} skipped${errHint}`,
      )
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const splitTotal = splitDrafts.reduce((sum, d) => sum + (Number(d.amount) || 0), 0)
  const splitTarget = active && splitForId === active.id ? Number(active.amount) : 0

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Transactions</h1>
          <p>
            Inline categorize · split · remember rules. WBC CAN and WBC USA stay separate. Import
            synoptic for cashbooks, or an adjusting pack for FY journals.
          </p>
        </div>
        <div className="toolbar">
          <label className="btn ghost">
            <input type="checkbox" checked={rememberRule} onChange={(e) => setRememberRule(e.target.checked)} />
            Remember rules
          </label>
          <button
            className="btn"
            onClick={() =>
              void api.applyRules().then(async (r) => {
                show(`Rules: ${r.categorized}`)
                await load()
              })
            }
          >
            Apply rules <span className="kbd">R</span>
          </button>
          <button
            className="btn"
            onClick={() =>
              void api.autoMatchIc().then(async (r) => {
                show(`IC matched: ${r.matched}`)
                await load()
              })
            }
          >
            Match IC <span className="kbd">I</span>
          </button>
          <button className="btn" disabled={!active} onClick={() => active && openSplit(active)}>
            Split <span className="kbd">S</span>
          </button>
          <label className="btn primary">
            Import CSV/Excel
            <input
              type="file"
              accept=".csv,.xlsx,.xls"
              hidden
              onChange={(e) => void onImport(e.target.files?.[0] ?? null)}
            />
          </label>
          <label className="btn">
            Import synoptic
            <input
              type="file"
              accept=".csv"
              hidden
              onChange={(e) => void onImportSynoptic(e.target.files?.[0] ?? null)}
            />
          </label>
          <label className="btn">
            Import adj pack
            <input
              type="file"
              accept=".csv"
              hidden
              onChange={(e) => void onImportAdjPack(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="filters">
        <input
          ref={searchRef}
          className="input"
          placeholder="Search description, payee, reference…  (/)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="select" value={entityId} onChange={(e) => setEntityId(e.target.value)}>
          <option value="">All entities</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.code} — {e.name}
            </option>
          ))}
        </select>
        <select className="select" value={bankId} onChange={(e) => setBankId(e.target.value)}>
          <option value="">All bank accounts</option>
          {banks.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name} ({b.currency})
            </option>
          ))}
        </select>
        <label className="btn ghost">
          <input type="checkbox" checked={uncategorizedOnly} onChange={(e) => setUncategorizedOnly(e.target.checked)} />
          Uncategorized
        </label>
        <label className="btn ghost">
          <input type="checkbox" checked={duplicatesOnly} onChange={(e) => setDuplicatesOnly(e.target.checked)} />
          Duplicates
        </label>
        <label className="btn ghost">
          <input type="checkbox" checked={unreconciledOnly} onChange={(e) => setUnreconciledOnly(e.target.checked)} />
          Unreconciled
        </label>
        {selected.size > 0 && (
          <AccountPicker
            accounts={accounts}
            placeholder={`Bulk categorize ${selected.size}…`}
            onSelect={(id) => void bulkCategorizeSelected(id)}
          />
        )}
      </div>

      <div className={`close-layout ${splitForId ? 'with-split' : ''}`}>
        <section className="panel">
          <div className="panel-header">
            <h2>
              {loading ? 'Loading…' : `${rows.length} transactions`}
              {selected.size > 0 && ` · ${selected.size} selected`}
            </h2>
            <span className="hint">Change Account / Dept / IC inline — no modal</span>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th></th>
                  <th>Date</th>
                  <th>Entity</th>
                  <th>Description</th>
                  <th>Account</th>
                  <th>Dept</th>
                  <th>IC Entity</th>
                  <th>Flags</th>
                  <th className="num">Amount</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((txn) => {
                  const locked = Boolean(txn.is_period_locked || txn.is_reconciled)
                  return (
                    <tr
                      key={txn.id}
                      className={`${selected.has(txn.id) || activeId === txn.id ? 'selected' : ''} ${locked ? 'locked-row' : ''}`}
                      onClick={(e) => {
                        if ((e.target as HTMLElement).tagName === 'SELECT') return
                        toggle(txn.id, e.metaKey || e.ctrlKey || e.shiftKey)
                      }}
                    >
                      <td>
                        <input
                          type="checkbox"
                          checked={selected.has(txn.id)}
                          onChange={(e) => {
                            e.stopPropagation()
                            toggle(txn.id, true)
                          }}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </td>
                      <td>{txn.txn_date}</td>
                      <td>
                        <span className="badge">{txn.entity_code}</span>
                      </td>
                      <td className="desc-cell">
                        <div>{txn.description}</div>
                        <div className="hint">{txn.bank_account_name ?? '—'}</div>
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        {txn.is_split ? (
                          <button className="btn ghost" onClick={() => openSplit(txn)}>
                            Split ({txn.splits?.length ?? 0})
                          </button>
                        ) : locked ? (
                          <span className="hint">
                            {txn.account_code ? `${txn.account_code} ${txn.account_name}` : '—'}
                          </span>
                        ) : (
                          <AccountPicker
                            accounts={accounts}
                            placeholder={
                              txn.account_code
                                ? `${txn.account_code} ${txn.account_name}`
                                : 'Categorize…'
                            }
                            onSelect={(id) => void inlineCategorize(txn, id)}
                          />
                        )}
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <select
                          className="select inline"
                          disabled={locked}
                          value={txn.department_id ?? ''}
                          onChange={(e) =>
                            void inlineDept(txn, e.target.value ? Number(e.target.value) : null)
                          }
                        >
                          <option value="">—</option>
                          {departments.map((d) => (
                            <option key={d.id} value={d.id}>
                              {d.code}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <select
                          className="select inline"
                          disabled={locked}
                          value={txn.counter_entity_id ?? ''}
                          onChange={(e) =>
                            void inlineCounterEntity(txn, e.target.value ? Number(e.target.value) : null)
                          }
                        >
                          <option value="">—</option>
                          {entities
                            .filter((e) => e.id !== txn.entity_id)
                            .map((e) => (
                              <option key={e.id} value={e.id}>
                                {e.code}
                              </option>
                            ))}
                        </select>
                      </td>
                      <td>
                        {txn.is_period_locked && <span className="badge danger">LOCKED</span>}
                        {txn.is_reconciled && !txn.is_period_locked && <span className="badge ok">RECON</span>}
                        {txn.is_duplicate && <span className="badge danger">DUP</span>}
                        {txn.intercompany_match_id && <span className="badge ok">IC</span>}
                        {txn.status === 'uncategorized' && <span className="badge open">OPEN</span>}
                      </td>
                      <td className="num">{money(txn.amount, txn.currency)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        {splitForId && active && (
          <aside className="panel split-panel">
            <div className="panel-header">
              <h2>Split #{active.id}</h2>
              <button className="btn ghost" onClick={() => setSplitForId(null)}>
                Close
              </button>
            </div>
            <div className="split-form">
              <p className="hint">{active.description}</p>
              <p className="hint">
                Target {money(active.amount, active.currency)} · Draft {money(splitTotal, active.currency)}
                {Math.abs(splitTotal - splitTarget) > 0.001 && (
                  <span className="badge danger"> out of balance</span>
                )}
              </p>
              {splitDrafts.map((line, idx) => (
                <div key={idx} className="split-line">
                  <select
                    className="select"
                    value={line.account_id}
                    onChange={(e) =>
                      setSplitDrafts((prev) =>
                        prev.map((p, i) => (i === idx ? { ...p, account_id: e.target.value } : p)),
                      )
                    }
                  >
                    <option value="">Account…</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.code} {a.name}
                      </option>
                    ))}
                  </select>
                  <input
                    className="input"
                    type="number"
                    step="0.01"
                    value={line.amount}
                    onChange={(e) =>
                      setSplitDrafts((prev) =>
                        prev.map((p, i) => (i === idx ? { ...p, amount: e.target.value } : p)),
                      )
                    }
                  />
                  <input
                    className="input"
                    placeholder="Memo"
                    value={line.memo}
                    onChange={(e) =>
                      setSplitDrafts((prev) =>
                        prev.map((p, i) => (i === idx ? { ...p, memo: e.target.value } : p)),
                      )
                    }
                  />
                  <button
                    className="btn ghost"
                    onClick={() => setSplitDrafts((prev) => prev.filter((_, i) => i !== idx))}
                    disabled={splitDrafts.length <= 1}
                  >
                    ✕
                  </button>
                </div>
              ))}
              <div className="form-actions">
                <button
                  className="btn"
                  onClick={() =>
                    setSplitDrafts((prev) => [...prev, { account_id: '', amount: '0.00', memo: '' }])
                  }
                >
                  Add line
                </button>
                <button
                  className="btn primary"
                  disabled={Math.abs(splitTotal - splitTarget) > 0.001}
                  onClick={() => void saveSplit()}
                >
                  Save split
                </button>
              </div>
            </div>
          </aside>
        )}
      </div>

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
