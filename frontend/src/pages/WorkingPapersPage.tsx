import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CheckCircle2, ClipboardList, ExternalLink, AlertTriangle } from 'lucide-react'
import { api, type BinderDocument, type BinderOut } from '../api'
import { usePeriod } from '../period/PeriodContext'
import { money } from '../lib/format'

const SECTION_LABEL: Record<string, string> = {
  asset: 'Assets',
  liability: 'Liabilities',
  equity: 'Equity',
  pnl: 'P&L',
}

export function WorkingPapersPage() {
  const { year, month, setPeriod, label, entityCode } = usePeriod()
  const [searchParams, setSearchParams] = useSearchParams()
  const [binder, setBinder] = useState<BinderOut | null>(null)
  const [doc, setDoc] = useState<BinderDocument | null>(null)
  const [activeKey, setActiveKey] = useState<string | null>(searchParams.get('key'))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Sync URL period → context
  useEffect(() => {
    const y = searchParams.get('year')
    const m = searchParams.get('month')
    if (y && m) {
      const yi = Number(y)
      const mi = Number(m)
      if (yi && mi && (yi !== year || mi !== month)) {
        setPeriod(yi, mi)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadBinder = useCallback(async () => {
    const data = await api.binder(year, month)
    setBinder(data)
    return data
  }, [year, month])

  const loadDoc = useCallback(
    async (key: string) => {
      const data = await api.binderDocument(key, year, month)
      setDoc(data)
      return data
    },
    [year, month],
  )

  useEffect(() => {
    setError(null)
    loadBinder()
      .then((data) => {
        const fromUrl = searchParams.get('key')
        const key =
          fromUrl && data.documents.some((d) => d.key === fromUrl)
            ? fromUrl
            : activeKey && data.documents.some((d) => d.key === activeKey)
              ? activeKey
              : data.documents[0]?.key
        if (key) {
          setActiveKey(key)
          return loadDoc(key)
        }
      })
      .catch((e: Error) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadBinder])

  useEffect(() => {
    const params = new URLSearchParams()
    params.set('year', String(year))
    params.set('month', String(month))
    if (activeKey) params.set('key', activeKey)
    setSearchParams(params, { replace: true })
  }, [year, month, activeKey, setSearchParams])

  const selectDoc = async (key: string) => {
    setActiveKey(key)
    setError(null)
    try {
      await loadDoc(key)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const persist = async (patch: {
    checked?: number[]
    notes?: string
    preparer?: string
    reviewer?: string
    status?: string
  }) => {
    if (!activeKey) return
    setSaving(true)
    try {
      const updated = await api.updateBinderDocument(activeKey, year, month, patch)
      setDoc(updated)
      await loadBinder()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const toggle = (idx: number) => {
    if (!doc) return
    const set = new Set(doc.checked)
    if (set.has(idx)) set.delete(idx)
    else set.add(idx)
    void persist({ checked: [...set].sort((a, b) => a - b) })
  }

  const summary = binder?.summary

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Binder</h1>
          <p>
            Working paper file for {entityCode ?? 'entity'} · {label} — live leads, procedures, and
            P/R sign-off.
          </p>
        </div>
        {summary && (
          <div className="toolbar">
            <span className="badge ok">
              {summary.prepared}/{summary.total} prepared
            </span>
            <span className="badge ok">{summary.reviewed} reviewed</span>
            {summary.untied > 0 && (
              <span className="badge open">{summary.untied} untied</span>
            )}
          </div>
        )}
      </div>

      {error && <div className="error">{error}</div>}

      <div className="wp-pack-layout">
        <section className="panel">
          <div className="panel-header">
            <h2>
              <ClipboardList size={16} /> Document manager
            </h2>
            <span className="hint">{binder?.documents.length ?? 0} docs</span>
          </div>
          <div className="wp-index">
            {binder?.documents.map((row) => (
              <button
                key={row.key}
                type="button"
                className={`wp-index-row ${activeKey === row.key ? 'active' : ''}`}
                onClick={() => void selectDoc(row.key)}
              >
                <span className="wp-ref">{row.wp_ref}</span>
                <span className="wp-index-title">
                  <strong>{row.title}</strong>
                  <span className="hint">
                    {SECTION_LABEL[row.section] ?? row.section} · {money(row.statement_amount, row.currency)}
                  </span>
                  <span className="wp-index-flags">
                    <span className={`badge ${row.status === 'reviewed' ? 'ok' : row.status === 'prepared' ? 'ok' : ''}`}>
                      {row.status}
                    </span>
                    {row.is_tied === true && <span className="badge ok">tied</span>}
                    {row.is_tied === false && <span className="badge open">untied</span>}
                    {row.close_status && (
                      <span className={`badge ${row.close_status === 'locked' ? 'ok' : 'open'}`}>
                        close {row.close_status}
                      </span>
                    )}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="panel wp-pack-detail">
          {!doc && <p className="hint" style={{ padding: '1rem' }}>Select a working paper.</p>}
          {doc && (
            <>
              <div className="panel-header">
                <h2>
                  <span className="wp-ref">{doc.wp_ref}</span> {doc.title}
                </h2>
                <div className="toolbar">
                  <Link className="btn ghost" to={doc.report_href}>
                    Statement <ExternalLink size={14} />
                  </Link>
                  {doc.close_href && (
                    <Link className="btn ghost" to={doc.close_href}>
                      Close pack <ExternalLink size={14} />
                    </Link>
                  )}
                </div>
              </div>

              <div className="wp-pack-body">
                <div className="tie-strip close-tie">
                  <div className="kpi">
                    <div className="kpi-label">
                      {doc.cash_schedule ? 'BS Cash' : 'Statement'}
                    </div>
                    <div className="kpi-value" style={{ fontSize: '1rem' }}>
                      {money(
                        doc.cash_schedule?.gl_statement_amount ??
                          doc.drill?.statement_amount ??
                          doc.statement_amount,
                        doc.currency,
                      )}
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">
                      {doc.cash_schedule ? 'Bank books' : 'Detail'}
                    </div>
                    <div className="kpi-value" style={{ fontSize: '1rem' }}>
                      {doc.cash_schedule
                        ? money(doc.cash_schedule.banks_book_reporting_total, doc.currency)
                        : doc.drill
                          ? money(doc.drill.detail_total, doc.currency)
                          : '—'}
                    </div>
                  </div>
                  <div className={`kpi ${doc.is_tied ? 'ok' : 'warn'}`}>
                    <div className="kpi-label">{doc.is_tied ? 'Tied' : 'Difference'}</div>
                    <div className="kpi-value" style={{ fontSize: '1rem' }}>
                      {doc.is_tied ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <CheckCircle2 size={14} /> Balanced
                        </span>
                      ) : doc.difference == null ? (
                        '—'
                      ) : (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <AlertTriangle size={14} /> {money(doc.difference, doc.currency)}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className={`kpi ${doc.status === 'reviewed' ? 'ok' : ''}`}>
                    <div className="kpi-label">
                      {doc.cash_schedule ? 'Banks' : 'Status'}
                    </div>
                    <div className="kpi-value" style={{ fontSize: '1rem' }}>
                      {doc.cash_schedule
                        ? `${doc.cash_schedule.banks_locked}/${doc.cash_schedule.banks_total} locked`
                        : doc.status}
                    </div>
                  </div>
                </div>

                {doc.cash_schedule && (doc.gate_messages?.length ?? 0) > 0 && (
                  <div className="cash-gate-banner">
                    <AlertTriangle size={14} />
                    <div>
                      <strong>Cash sign-off gates</strong>
                      <ul>
                        {doc.gate_messages!.map((msg) => (
                          <li key={msg}>{msg}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}

                <div className="wp-pack-meta">
                  <div>
                    <span>Purpose</span>
                    <p>{doc.purpose}</p>
                  </div>
                  <div>
                    <span>Objective</span>
                    <p>{doc.objective}</p>
                  </div>
                  <div>
                    <span>Tie-out</span>
                    <p className="wp-tieout">{doc.tie_out}</p>
                  </div>
                </div>

                <div className="wp-pack-grid">
                  <div>
                    <div className="wp-pack-section-head">
                      <h3>Procedures</h3>
                      <span className="hint">
                        {doc.procedures_done}/{doc.procedure_count}
                        {saving ? ' · saving…' : ''}
                      </span>
                    </div>
                    <ol className="wp-procedure-list">
                      {doc.procedures.map((step, idx) => (
                        <li key={idx} className={doc.checked.includes(idx) ? 'done' : ''}>
                          <label>
                            <input
                              type="checkbox"
                              checked={doc.checked.includes(idx)}
                              onChange={() => toggle(idx)}
                            />
                            <span>{step}</span>
                          </label>
                        </li>
                      ))}
                    </ol>

                    {doc.cash_schedule && (
                      <>
                        <div className="wp-pack-section-head" style={{ marginTop: '1.1rem' }}>
                          <h3>Bank recon schedule</h3>
                          <span className="hint">
                            {doc.cash_schedule.banks_tied}/{doc.cash_schedule.banks_total} tied ·{' '}
                            {doc.cash_schedule.close_status}
                          </span>
                        </div>
                        <div className="table-wrap" style={{ maxHeight: 320 }}>
                          <table className="data cash-recon-table">
                            <thead>
                              <tr>
                                <th>Bank</th>
                                <th className="num">Book</th>
                                <th className="num">Statement</th>
                                <th className="num">Diff</th>
                                <th>Status</th>
                                <th></th>
                              </tr>
                            </thead>
                            <tbody>
                              {doc.cash_schedule.banks.map((bank) => (
                                <tr
                                  key={bank.bank_account_id}
                                  className={bank.is_tied ? '' : 'recon-health-row below'}
                                >
                                  <td>
                                    <strong>{bank.bank_account_name}</strong>
                                    <div className="hint">
                                      {bank.entity_code} · {bank.currency}
                                      {bank.uncleared_count > 0 && ` · ${bank.uncleared_count} uncleared`}
                                      {bank.prior_item_count > 0 && ` · ${bank.prior_item_count} PRIOR`}
                                      {bank.blocking_count > 0 && ` · ${bank.blocking_count} blocking`}
                                    </div>
                                  </td>
                                  <td className="num">{money(bank.book_balance, bank.currency)}</td>
                                  <td className="num">
                                    {bank.statement_ending_balance == null
                                      ? '—'
                                      : money(bank.statement_ending_balance, bank.currency)}
                                  </td>
                                  <td className="num">
                                    {bank.difference == null ? '—' : money(bank.difference, bank.currency)}
                                  </td>
                                  <td>
                                    <span
                                      className={`badge ${bank.is_locked ? 'ok' : bank.is_tied ? 'ok' : 'open'}`}
                                    >
                                      {bank.is_locked
                                        ? 'locked'
                                        : bank.can_lock
                                          ? 'ready'
                                          : bank.status.replace('_', ' ')}
                                    </span>
                                  </td>
                                  <td>
                                    <Link className="btn ghost" to={bank.href}>
                                      Open <ExternalLink size={12} />
                                    </Link>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                            <tfoot>
                              <tr>
                                <td>BS cash vs bank books ({doc.cash_schedule.reporting_currency})</td>
                                <td className="num" colSpan={2}>
                                  {money(doc.cash_schedule.gl_statement_amount)} vs{' '}
                                  {money(doc.cash_schedule.banks_book_reporting_total)}
                                </td>
                                <td className="num">
                                  {money(doc.cash_schedule.gl_vs_books_difference)}
                                </td>
                                <td colSpan={2}>
                                  <span className={`badge ${doc.cash_schedule.gl_agrees ? 'ok' : 'open'}`}>
                                    {doc.cash_schedule.gl_agrees ? 'GL agrees' : 'GL mismatch'}
                                  </span>
                                </td>
                              </tr>
                            </tfoot>
                          </table>
                        </div>
                      </>
                    )}

                    {!doc.cash_schedule && doc.drill && doc.drill.lines.length > 0 && (
                      <>
                        <div className="wp-pack-section-head" style={{ marginTop: '1.1rem' }}>
                          <h3>Supporting schedule</h3>
                          <span className="hint">{doc.drill.row_count} items</span>
                        </div>
                        <div className="table-wrap" style={{ maxHeight: 280 }}>
                          <table className="data">
                            <thead>
                              <tr>
                                <th>Date</th>
                                <th>Description</th>
                                <th>Account</th>
                                <th className="num">Amount</th>
                              </tr>
                            </thead>
                            <tbody>
                              {doc.drill.lines.slice(0, 50).map((row, i) => (
                                <tr key={`${row.transaction_id}-${i}`}>
                                  <td>{row.txn_date}</td>
                                  <td>
                                    {row.description}
                                    {row.entity_code && (
                                      <div className="hint">{row.entity_code}</div>
                                    )}
                                  </td>
                                  <td className="hint">
                                    {row.account_code} {row.account_name}
                                  </td>
                                  <td className="num">{money(row.signed_amount)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  </div>

                  <div>
                    <div className="wp-pack-section-head">
                      <h3>Evidence</h3>
                    </div>
                    <ul className="wp-evidence-list">
                      {doc.evidence.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>

                    <div className="wp-pack-section-head" style={{ marginTop: '1.1rem' }}>
                      <h3>Sign-off</h3>
                    </div>
                    <div className="wp-signoff">
                      <label>
                        Preparer
                        <input
                          value={doc.preparer ?? ''}
                          onChange={(e) => setDoc({ ...doc, preparer: e.target.value })}
                          onBlur={(e) => void persist({ preparer: e.target.value })}
                          placeholder="Initials"
                        />
                      </label>
                      <label>
                        Reviewer
                        <input
                          value={doc.reviewer ?? ''}
                          onChange={(e) => setDoc({ ...doc, reviewer: e.target.value })}
                          onBlur={(e) => void persist({ reviewer: e.target.value })}
                          placeholder="Initials"
                        />
                      </label>
                    </div>
                    <div className="toolbar" style={{ marginBottom: '0.65rem' }}>
                      <button
                        className="btn"
                        disabled={
                          doc.status === 'prepared' ||
                          doc.status === 'reviewed' ||
                          doc.can_prepare === false
                        }
                        title={
                          doc.can_prepare === false
                            ? (doc.gate_messages || []).join('; ') || 'Cash recon not ready'
                            : undefined
                        }
                        onClick={() =>
                          void persist({ status: 'prepared', preparer: doc.preparer || 'C' })
                        }
                      >
                        Mark prepared
                      </button>
                      <button
                        className="btn primary"
                        disabled={doc.status === 'reviewed' || doc.can_review === false}
                        title={
                          doc.can_review === false
                            ? (doc.gate_messages || []).join('; ') || 'Lock banks before review'
                            : undefined
                        }
                        onClick={() => {
                          const prep = (doc.preparer || 'C').trim()
                          let rev = (doc.reviewer || 'R').trim()
                          if (rev.toUpperCase() === prep.toUpperCase()) rev = `${rev}2`
                          void persist({ status: 'reviewed', preparer: prep, reviewer: rev })
                        }}
                      >
                        Mark reviewed
                      </button>
                    </div>
                    {doc.key === 'cash' && (
                      <p className="hint" style={{ marginBottom: '0.65rem' }}>
                        Prepare requires every bank ready/locked with diff = 0 and BS cash = bank books.
                        Review requires all banks locked and a different reviewer.
                      </p>
                    )}
                    <label className="wp-notes">
                      Notes
                      <textarea
                        value={doc.notes ?? ''}
                        rows={4}
                        onChange={(e) => setDoc({ ...doc, notes: e.target.value })}
                        onBlur={(e) => void persist({ notes: e.target.value })}
                        placeholder="Exceptions, conclusions, open items…"
                      />
                    </label>
                    {(doc.preparer_at || doc.reviewer_at) && (
                      <p className="hint" style={{ marginTop: '0.5rem' }}>
                        {doc.preparer_at && <>Prepared {new Date(doc.preparer_at).toLocaleString()} · </>}
                        {doc.reviewer_at && <>Reviewed {new Date(doc.reviewer_at).toLocaleString()}</>}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
