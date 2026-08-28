import { useEffect, useMemo, useState } from 'react'
import { api, type Account, type BankAccount, type Entity, type FxRate, type Rule } from '../api'
import { useToast } from '../hooks/useToast'

type RuleDraft = {
  name: string
  priority: string
  is_active: boolean
  match_description_contains: string
  match_entity_id: string
  match_bank_account_id: string
  assign_account_id: string
  assign_counter_entity_id: string
}

const emptyDraft = (): RuleDraft => ({
  name: '',
  priority: '50',
  is_active: true,
  match_description_contains: '',
  match_entity_id: '',
  match_bank_account_id: '',
  assign_account_id: '',
  assign_counter_entity_id: '',
})

function ruleToDraft(rule: Rule): RuleDraft {
  return {
    name: rule.name,
    priority: String(rule.priority),
    is_active: rule.is_active,
    match_description_contains: rule.match_description_contains ?? '',
    match_entity_id: rule.match_entity_id != null ? String(rule.match_entity_id) : '',
    match_bank_account_id: rule.match_bank_account_id != null ? String(rule.match_bank_account_id) : '',
    assign_account_id: String(rule.assign_account_id),
    assign_counter_entity_id:
      rule.assign_counter_entity_id != null ? String(rule.assign_counter_entity_id) : '',
  }
}

function draftPayload(draft: RuleDraft) {
  return {
    name: draft.name.trim(),
    priority: Number(draft.priority) || 100,
    is_active: draft.is_active,
    match_description_contains: draft.match_description_contains.trim() || null,
    match_entity_id: draft.match_entity_id ? Number(draft.match_entity_id) : null,
    match_bank_account_id: draft.match_bank_account_id ? Number(draft.match_bank_account_id) : null,
    assign_account_id: Number(draft.assign_account_id),
    assign_counter_entity_id: draft.assign_counter_entity_id
      ? Number(draft.assign_counter_entity_id)
      : null,
  }
}

export function SettingsPage() {
  const [rules, setRules] = useState<Rule[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [entities, setEntities] = useState<Entity[]>([])
  const [banks, setBanks] = useState<BankAccount[]>([])
  const [fx, setFx] = useState<FxRate[]>([])
  const [audit, setAudit] = useState<Array<Record<string, unknown>>>([])
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<number | 'new' | null>(null)
  const [draft, setDraft] = useState<RuleDraft>(emptyDraft())
  const [fxDraft, setFxDraft] = useState({
    from_currency: 'USD',
    to_currency: 'CAD',
    rate_date: '2026-07-31',
    rate: '',
    rate_type: 'closing',
  })
  const { toast, show } = useToast()

  const reload = () =>
    Promise.all([
      api.rules(),
      api.accounts(),
      api.entities(),
      api.bankAccounts(),
      api.fxRates(),
      api.auditLog(),
    ]).then(([r, a, e, b, rates, log]) => {
      setRules(r)
      setAccounts(a)
      setEntities(e)
      setBanks(b)
      setFx(rates)
      setAudit(log)
    })

  useEffect(() => {
    reload().catch((err: Error) => setError(err.message))
  }, [])

  const accountLabel = (id: number) => {
    const a = accounts.find((x) => x.id === id)
    return a ? `${a.code} ${a.name}` : String(id)
  }
  const entityLabel = (id: number | null | undefined) => {
    if (id == null) return 'All entities'
    return entities.find((e) => e.id === id)?.code ?? String(id)
  }
  const bankLabel = (id: number | null | undefined) => {
    if (id == null) return 'All banks'
    return banks.find((b) => b.id === id)?.name ?? String(id)
  }

  const saveRule = async () => {
    if (!draft.name.trim() || !draft.assign_account_id) {
      setError('Rule needs a name and an account')
      return
    }
    setError(null)
    try {
      const body = draftPayload(draft)
      if (editingId === 'new') {
        await api.createRule(body)
        show('Rule created')
      } else if (typeof editingId === 'number') {
        await api.updateRule(editingId, body)
        show('Rule saved')
      }
      setEditingId(null)
      setDraft(emptyDraft())
      await reload()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const toggleActive = async (rule: Rule) => {
    setError(null)
    try {
      await api.updateRule(rule.id, { is_active: !rule.is_active })
      await reload()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const removeRule = async (rule: Rule) => {
    setError(null)
    try {
      await api.deleteRule(rule.id)
      if (editingId === rule.id) {
        setEditingId(null)
        setDraft(emptyDraft())
      }
      show('Rule deleted')
      await reload()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const addFx = async () => {
    if (!fxDraft.rate) {
      setError('Enter an FX rate')
      return
    }
    setError(null)
    try {
      await api.createFxRate({
        ...fxDraft,
        from_currency: fxDraft.from_currency.toUpperCase(),
        to_currency: fxDraft.to_currency.toUpperCase(),
        rate: Number(fxDraft.rate),
      })
      setFxDraft((d) => ({ ...d, rate: '' }))
      show('FX rate saved')
      await reload()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const highlighted = useMemo(() => {
    const usdCad = fx.filter((r) => r.from_currency === 'USD' && r.to_currency === 'CAD')
    const closing = usdCad.find((r) => r.rate_type === 'closing')
    const average = usdCad.find((r) => r.rate_type === 'average')
    return { closing, average }
  }, [fx])

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Edit categorization rules and look up FX rates used on the statements.</p>
        </div>
      </div>
      {error && <div className="error">{error}</div>}

      <section className="panel">
        <div className="panel-header">
          <h2>Rules</h2>
          <button
            className="btn primary"
            type="button"
            onClick={() => {
              setEditingId('new')
              setDraft({
                ...emptyDraft(),
                assign_account_id: accounts[0] ? String(accounts[0].id) : '',
              })
            }}
          >
            New rule
          </button>
        </div>
        {editingId != null && (
          <div className="rule-form">
            <div className="rule-form-grid">
              <label>
                Name
                <input
                  className="input"
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </label>
              <label>
                Priority
                <input
                  className="input"
                  type="number"
                  value={draft.priority}
                  onChange={(e) => setDraft({ ...draft, priority: e.target.value })}
                />
              </label>
              <label>
                Match contains
                <input
                  className="input"
                  value={draft.match_description_contains}
                  onChange={(e) => setDraft({ ...draft, match_description_contains: e.target.value })}
                />
              </label>
              <label>
                Assign account
                <select
                  className="select"
                  value={draft.assign_account_id}
                  onChange={(e) => setDraft({ ...draft, assign_account_id: e.target.value })}
                >
                  <option value="">Select…</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} {a.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Entity
                <select
                  className="select"
                  value={draft.match_entity_id}
                  onChange={(e) => setDraft({ ...draft, match_entity_id: e.target.value })}
                >
                  <option value="">All entities</option>
                  {entities.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.code}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Bank (optional)
                <select
                  className="select"
                  value={draft.match_bank_account_id}
                  onChange={(e) => setDraft({ ...draft, match_bank_account_id: e.target.value })}
                >
                  <option value="">All banks of the entity</option>
                  {banks
                    .filter((b) => !draft.match_entity_id || String(b.entity_id) === draft.match_entity_id)
                    .map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Counter-entity (IC)
                <select
                  className="select"
                  value={draft.assign_counter_entity_id}
                  onChange={(e) => setDraft({ ...draft, assign_counter_entity_id: e.target.value })}
                >
                  <option value="">None</option>
                  {entities.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.code}
                    </option>
                  ))}
                </select>
              </label>
              <label className="rule-active">
                <input
                  type="checkbox"
                  checked={draft.is_active}
                  onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
                />
                Active
              </label>
            </div>
            <div className="form-actions">
              <button
                className="btn ghost"
                type="button"
                onClick={() => {
                  setEditingId(null)
                  setDraft(emptyDraft())
                }}
              >
                Cancel
              </button>
              <button className="btn primary" type="button" onClick={() => void saveRule()}>
                Save rule
              </button>
            </div>
          </div>
        )}
        <div className="table-wrap" style={{ maxHeight: 420 }}>
          <table className="data">
            <thead>
              <tr>
                <th>On</th>
                <th>Priority</th>
                <th>Name</th>
                <th>Match</th>
                <th>Scope</th>
                <th>Assign</th>
                <th className="num">Hits</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id} className={r.is_active ? '' : 'dim-row'}>
                  <td>
                    <input type="checkbox" checked={r.is_active} onChange={() => void toggleActive(r)} />
                  </td>
                  <td>{r.priority}</td>
                  <td>{r.name}</td>
                  <td>{r.match_description_contains ?? '—'}</td>
                  <td>
                    {entityLabel(r.match_entity_id)} · {bankLabel(r.match_bank_account_id)}
                  </td>
                  <td>
                    {accountLabel(r.assign_account_id)}
                    {r.assign_counter_entity_id != null
                      ? ` · IC ${entityLabel(r.assign_counter_entity_id)}`
                      : ''}
                  </td>
                  <td className="num">{r.hit_count}</td>
                  <td>
                    <div className="inbox-row-actions">
                      <button
                        className="btn ghost"
                        type="button"
                        onClick={() => {
                          setEditingId(r.id)
                          setDraft(ruleToDraft(r))
                        }}
                      >
                        Edit
                      </button>
                      <button className="btn ghost" type="button" onClick={() => void removeRule(r)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel" style={{ marginTop: '0.85rem' }}>
        <div className="panel-header">
          <h2>FX rates</h2>
          <span className="hint">
            USD→CAD closing {highlighted.closing ? Number(highlighted.closing.rate).toFixed(4) : '—'}
            {highlighted.closing ? ` · ${highlighted.closing.rate_date}` : ''}
            {' · '}
            average {highlighted.average ? Number(highlighted.average.rate).toFixed(4) : '—'}
          </span>
        </div>
        <p className="hint" style={{ padding: '0 1rem' }}>
          P&amp;L uses average; the balance sheet, cash, and intercompany use closing. Missing pairs stay
          missing — nothing is assumed at 1.
        </p>
        <div className="rule-form">
          <div className="rule-form-grid fx-form-grid">
            <label>
              From
              <input
                className="input"
                value={fxDraft.from_currency}
                onChange={(e) => setFxDraft({ ...fxDraft, from_currency: e.target.value })}
              />
            </label>
            <label>
              To
              <input
                className="input"
                value={fxDraft.to_currency}
                onChange={(e) => setFxDraft({ ...fxDraft, to_currency: e.target.value })}
              />
            </label>
            <label>
              Date
              <input
                className="input"
                type="date"
                value={fxDraft.rate_date}
                onChange={(e) => setFxDraft({ ...fxDraft, rate_date: e.target.value })}
              />
            </label>
            <label>
              Type
              <select
                className="select"
                value={fxDraft.rate_type}
                onChange={(e) => setFxDraft({ ...fxDraft, rate_type: e.target.value })}
              >
                <option value="closing">closing</option>
                <option value="average">average</option>
                <option value="spot">spot</option>
              </select>
            </label>
            <label>
              Rate
              <input
                className="input"
                type="number"
                step="0.0001"
                value={fxDraft.rate}
                onChange={(e) => setFxDraft({ ...fxDraft, rate: e.target.value })}
              />
            </label>
            <div className="form-actions" style={{ alignSelf: 'end', margin: 0 }}>
              <button className="btn" type="button" onClick={() => void addFx()}>
                Add rate
              </button>
            </div>
          </div>
        </div>
        <div className="table-wrap" style={{ maxHeight: 320 }}>
          <table className="data">
            <thead>
              <tr>
                <th>Pair</th>
                <th>Date</th>
                <th>Type</th>
                <th className="num">Rate</th>
              </tr>
            </thead>
            <tbody>
              {fx.map((r) => (
                <tr
                  key={r.id}
                  className={
                    r.from_currency === 'USD' && r.to_currency === 'CAD' && r.rate_type === 'closing'
                      ? 'selected'
                      : ''
                  }
                >
                  <td>
                    {r.from_currency}→{r.to_currency}
                  </td>
                  <td>{r.rate_date}</td>
                  <td>{r.rate_type}</td>
                  <td className="num">{Number(r.rate).toFixed(6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid-2" style={{ marginTop: '0.85rem' }}>
        <section className="panel">
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

        <section className="panel">
          <div className="panel-header">
            <h2>Audit log</h2>
          </div>
          <div className="table-wrap" style={{ maxHeight: 320 }}>
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
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
