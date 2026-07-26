import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  api,
  type Account,
  type BankAccount,
  type Entity,
  type Transaction,
} from '../api'
import { useToast } from '../hooks/useToast'
import { money } from '../lib/format'

export function TransactionsPage() {
  const [params, setParams] = useSearchParams()
  const [rows, setRows] = useState<Transaction[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [entities, setEntities] = useState<Entity[]>([])
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
  const [showCategorize, setShowCategorize] = useState(false)
  const [accountPick, setAccountPick] = useState('')
  const [createRule, setCreateRule] = useState(true)
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
    Promise.all([api.accounts(), api.entities(), api.bankAccounts()]).then(([a, e, b]) => {
      setAccounts(a)
      setEntities(e)
      setBanks(b)
    })
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

  const accountMap = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts])

  const toggle = (id: number, additive: boolean) => {
    setActiveId(id)
    setSelected((prev) => {
      const next = new Set(additive ? prev : [])
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const openCategorize = () => {
    if (selected.size === 0 && activeId) setSelected(new Set([activeId]))
    if (selected.size === 0 && !activeId) {
      show('Select one or more transactions first')
      return
    }
    setShowCategorize(true)
  }

  const applyCategorize = async () => {
    const ids = [...selected]
    if (!accountPick || ids.length === 0) return
    try {
      if (ids.length === 1) {
        await api.categorize(ids[0], {
          account_id: Number(accountPick),
          create_rule: createRule,
        })
      } else {
        await api.bulkCategorize(ids, Number(accountPick), createRule)
      }
      setShowCategorize(false)
      setSelected(new Set())
      show(`Categorized ${ids.length} transaction${ids.length > 1 ? 's' : ''}`)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
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
      if (e.key.toLowerCase() === 'c') {
        e.preventDefault()
        openCategorize()
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
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, activeId, accountPick, load])

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

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Transactions</h1>
          <p>Excel-like grid for categorization, splits, duplicates, and intercompany matching.</p>
        </div>
        <div className="toolbar">
          <button className="btn" onClick={() => void api.applyRules().then(async (r) => { show(`Rules: ${r.categorized}`); await load() })}>
            Apply rules <span className="kbd">R</span>
          </button>
          <button className="btn" onClick={() => void api.autoMatchIc().then(async (r) => { show(`IC matched: ${r.matched}`); await load() })}>
            Match IC <span className="kbd">I</span>
          </button>
          <button className="btn primary" onClick={openCategorize}>
            Categorize <span className="kbd">C</span>
          </button>
          <label className="btn">
            Import CSV/Excel
            <input
              type="file"
              accept=".csv,.xlsx,.xls"
              hidden
              onChange={(e) => void onImport(e.target.files?.[0] ?? null)}
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
      </div>

      <section className="panel">
        <div className="panel-header">
          <h2>
            {loading ? 'Loading…' : `${rows.length} transactions`}
            {selected.size > 0 && ` · ${selected.size} selected`}
          </h2>
          <span className="hint">Click to select · Shift/Ctrl multi-select · one-click recode</span>
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th></th>
                <th>Date</th>
                <th>Entity</th>
                <th>Bank</th>
                <th>Description</th>
                <th>Account</th>
                <th>Status</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((txn) => {
                const acct = txn.account_id ? accountMap.get(txn.account_id) : undefined
                return (
                  <tr
                    key={txn.id}
                    className={selected.has(txn.id) || activeId === txn.id ? 'selected' : ''}
                    onClick={(e) => toggle(txn.id, e.metaKey || e.ctrlKey || e.shiftKey)}
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
                    <td>{txn.bank_account_name ?? '—'}</td>
                    <td>
                      {txn.description}
                      {txn.is_duplicate && <span className="badge danger"> DUP</span>}
                      {txn.is_split && <span className="badge"> SPLIT</span>}
                      {txn.intercompany_match_id && <span className="badge ok"> IC</span>}
                    </td>
                    <td>
                      {txn.is_split
                        ? 'Split'
                        : acct
                          ? `${acct.code} ${acct.name}`
                          : txn.account_name
                            ? `${txn.account_code} ${txn.account_name}`
                            : '—'}
                    </td>
                    <td>
                      <span className={`badge ${txn.status === 'uncategorized' ? 'open' : 'ok'}`}>{txn.status}</span>
                    </td>
                    <td className="num">{money(txn.amount, txn.currency)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      {showCategorize && (
        <div className="modal-backdrop" onClick={() => setShowCategorize(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Categorize {selected.size || 1} transaction(s)</h3>
            <div className="form-row">
              <label>Reporting account</label>
              <select className="select" value={accountPick} onChange={(e) => setAccountPick(e.target.value)} autoFocus>
                <option value="">Select account…</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.code} — {a.name}
                  </option>
                ))}
              </select>
            </div>
            <label className="btn ghost" style={{ justifyContent: 'flex-start' }}>
              <input type="checkbox" checked={createRule} onChange={(e) => setCreateRule(e.target.checked)} />
              Remember this categorization (create rule)
            </label>
            <div className="form-actions">
              <button className="btn ghost" onClick={() => setShowCategorize(false)}>
                Cancel
              </button>
              <button className="btn primary" disabled={!accountPick} onClick={() => void applyCategorize()}>
                Apply
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
