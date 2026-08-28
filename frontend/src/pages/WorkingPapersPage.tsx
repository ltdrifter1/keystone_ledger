import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CheckCircle2, ClipboardList, ExternalLink, AlertTriangle, Paperclip, BookPlus } from 'lucide-react'
import { api, type Account, type BinderDocument, type BinderOut } from '../api'
import { useEngagement } from '../period/PeriodContext'
import { useSession } from '../session/SessionContext'
import { JournalVoucherModal } from '../components/JournalVoucherModal'
import { money } from '../lib/format'

const SECTION_LABEL: Record<string, string> = {
  asset: 'Assets',
  liability: 'Liabilities',
  equity: 'Equity',
  pnl: 'P&L',
}

export function WorkingPapersPage() {
  const { year, month, setPeriod, label, entityCode, entityId } = useEngagement()
  const { user } = useSession()
  const [searchParams, setSearchParams] = useSearchParams()
  const [binder, setBinder] = useState<BinderOut | null>(null)
  const [doc, setDoc] = useState<BinderDocument | null>(null)
  const [activeKey, setActiveKey] = useState<string | null>(searchParams.get('key'))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [journalOpen, setJournalOpen] = useState(false)

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

  useEffect(() => {
    api.accounts().then(setAccounts).catch(() => undefined)
  }, [])

  const loadBinder = useCallback(async () => {
    const data = await api.binder(year, month, entityId || undefined)
    setBinder(data)
    return data
  }, [year, month, entityId])

  const loadDoc = useCallback(
    async (key: string) => {
      const data = await api.binderDocument(key, year, month, entityId || undefined)
      setDoc(data)
      return data
    },
    [year, month, entityId],
  )

  useEffect(() => {
    if (!entityId) return
    setError(null)
    setLoading(true)
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
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadBinder])

  useEffect(() => {
    const params = new URLSearchParams()
    params.set('year', String(year))
    params.set('month', String(month))
    if (activeKey) params.set('key', activeKey)
    if (entityId) params.set('entity_id', entityId)
    setSearchParams(params, { replace: true })
  }, [year, month, activeKey, entityId, setSearchParams])

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
      const updated = await api.updateBinderDocument(
        activeKey,
        year,
        month,
        patch,
        entityId || undefined,
      )
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
      {loading && !binder && <p className="hint">Loading binder…</p>}

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
                      Work desk <ExternalLink size={14} />
                    </Link>
                  )}
                  <button className="btn" type="button" onClick={() => setJournalOpen(true)}>
                    <BookPlus size={14} /> Adjusting journal
                  </button>
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

                    {!doc.cash_schedule && doc.schedule && (
                      <WpLiveSchedule schedule={doc.schedule} currency={doc.currency} />
                    )}

                    {!doc.cash_schedule && !doc.schedule && doc.drill && doc.drill.lines.length > 0 && (
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
                      <span className="hint">{doc.attachment_count ?? 0} file(s)</span>
                    </div>
                    <ul className="wp-evidence-list">
                      {(doc.attachments || []).map((file) => (
                        <li key={file.id}>
                          <Paperclip size={12} /> {file.filename}
                          <span className="hint"> · {file.uploaded_by}</span>
                        </li>
                      ))}
                    </ul>
                    <label className="btn ghost" style={{ margin: '0.35rem 0 0.75rem' }}>
                      Upload support
                      <input
                        type="file"
                        hidden
                        onChange={(e) => {
                          const file = e.target.files?.[0]
                          if (!file || !doc.document_id) return
                          void api
                            .uploadAttachment('working_paper_documents', doc.document_id, file)
                            .then(async () => {
                              if (activeKey) await loadDoc(activeKey)
                            })
                            .catch((err: Error) => setError(err.message))
                          e.target.value = ''
                        }}
                      />
                    </label>
                    <ul className="wp-evidence-list faint">
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
                        <input value={doc.preparer ?? ''} readOnly placeholder="—" />
                      </label>
                      <label>
                        Reviewer
                        <input value={doc.reviewer ?? ''} readOnly placeholder="—" />
                      </label>
                    </div>
                    <p className="hint">
                      Signed in as {user ? `${user.initials} · ${user.display_name}` : '…'}. Switch user in the
                      sidebar to review.
                    </p>
                    <div className="toolbar" style={{ marginBottom: '0.65rem' }}>
                      {doc.status === 'prepared' || doc.status === 'reviewed' ? (
                        <span className="badge ok">Prepared · {doc.preparer}</span>
                      ) : (
                        <button
                          className="btn"
                          disabled={doc.can_prepare === false}
                          title={
                            doc.can_prepare === false
                              ? (doc.gate_messages || []).join('; ') || 'Not ready'
                              : undefined
                          }
                          onClick={() =>
                            void persist({
                              status: 'prepared',
                              preparer: user?.initials,
                            })
                          }
                        >
                          Mark prepared
                        </button>
                      )}
                      {doc.status === 'reviewed' ? (
                        <span className="badge ok">Reviewed · {doc.reviewer}</span>
                      ) : (
                        <button
                          className="btn primary"
                          disabled={
                            doc.can_review === false ||
                            !doc.preparer ||
                            (user?.initials || '').toUpperCase() === (doc.preparer || '').toUpperCase()
                          }
                          title={
                            (user?.initials || '').toUpperCase() === (doc.preparer || '').toUpperCase()
                              ? 'Reviewer must be a different person — switch user'
                              : doc.can_review === false
                                ? (doc.gate_messages || []).join('; ') || 'Not ready'
                                : undefined
                          }
                          onClick={() =>
                            void persist({
                              status: 'reviewed',
                              reviewer: user?.initials,
                            })
                          }
                        >
                          Mark reviewed
                        </button>
                      )}
                    </div>
                    {(doc.gate_messages?.length ?? 0) > 0 && doc.key !== 'cash' && (
                      <p className="hint" style={{ marginBottom: '0.65rem' }}>
                        {doc.gate_messages!.join(' · ')}
                      </p>
                    )}
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
      <JournalVoucherModal
        open={journalOpen}
        accounts={accounts}
        workingPaperKey={activeKey || undefined}
        onClose={() => setJournalOpen(false)}
        onPosted={() => {
          if (activeKey) void loadDoc(activeKey)
          void loadBinder()
        }}
      />
    </div>
  )
}

function WpLiveSchedule({
  schedule,
  currency,
}: {
  schedule: NonNullable<BinderDocument['schedule']>
  currency: string
}) {
  const kindLabel =
    schedule.kind === 'aging'
      ? 'Aging'
      : schedule.kind === 'rollforward'
        ? 'Rollforward'
        : schedule.kind === 'intercompany'
          ? 'Monthly intercompany rec'
          : 'Lead schedule'
  return (
    <>
      <div className="wp-pack-section-head" style={{ marginTop: '1.1rem' }}>
        <h3>{kindLabel}</h3>
        <span className="hint">
          {schedule.row_count ?? 0} items · {schedule.is_tied ? 'tied' : 'untied'}
        </span>
      </div>
      {schedule.kind === 'aging' && (
        <div className="table-wrap" style={{ maxHeight: 320 }}>
          <table className="data cash-recon-table">
            <thead>
              <tr>
                <th>Counterparty</th>
                <th className="num">Current</th>
                <th className="num">31–60</th>
                <th className="num">61–90</th>
                <th className="num">91+</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {(schedule.parties || []).map((p) => (
                <tr key={p.counterparty}>
                  <td>
                    {p.counterparty}
                    <div className="hint">{p.count} items</div>
                  </td>
                  <td className="num">{money(p.current, currency)}</td>
                  <td className="num">{money(p.days_31_60, currency)}</td>
                  <td className="num">{money(p.days_61_90, currency)}</td>
                  <td className="num">{money(p.days_91_plus, currency)}</td>
                  <td className="num">{money(p.total, currency)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>vs statement {money(schedule.gl_amount, currency)}</td>
                <td className="num" colSpan={4}>
                  {schedule.buckets
                    ? `${money(schedule.buckets.current)} / ${money(schedule.buckets.days_31_60)} / ${money(schedule.buckets.days_61_90)} / ${money(schedule.buckets.days_91_plus)}`
                    : '—'}
                </td>
                <td className="num">{money(schedule.schedule_total ?? 0, currency)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {schedule.kind === 'rollforward' && (
        <div className="table-wrap" style={{ maxHeight: 320 }}>
          <table className="data cash-recon-table">
            <thead>
              <tr>
                <th>Account</th>
                <th className="num">Opening</th>
                <th className="num">Additions</th>
                <th className="num">Reductions</th>
                <th className="num">Closing</th>
              </tr>
            </thead>
            <tbody>
              {(schedule.accounts || []).map((a) => (
                <tr key={a.account_code}>
                  <td>
                    {a.account_code} {a.account_name}
                  </td>
                  <td className="num">{money(a.opening ?? 0, currency)}</td>
                  <td className="num">{money(a.additions ?? 0, currency)}</td>
                  <td className="num">{money(a.reductions ?? 0, currency)}</td>
                  <td className="num">{money(a.closing ?? 0, currency)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>Tie to statement {money(schedule.gl_amount, currency)}</td>
                <td className="num">{money(schedule.opening ?? 0, currency)}</td>
                <td className="num">{money(schedule.additions ?? 0, currency)}</td>
                <td className="num">{money(schedule.reductions ?? 0, currency)}</td>
                <td className="num">{money(schedule.closing ?? 0, currency)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {schedule.kind === 'intercompany' && schedule.ic_mirror && (
        <div className="table-wrap" style={{ marginBottom: '0.75rem' }}>
          <table className="data cash-recon-table">
            <thead>
              <tr>
                <th>Monthly IC mirror ({schedule.ic_mirror.currency})</th>
                <th className="num">{schedule.ic_mirror.entity_code} AR</th>
                <th className="num">{schedule.ic_mirror.entity_code} AP</th>
                <th className="num">{schedule.ic_mirror.counter_entity_code} net</th>
                <th className="num">Difference</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  {schedule.ic_mirror.is_mirrored ? (
                    <span className="badge ok">mirrored</span>
                  ) : (
                    <span className="badge open">off</span>
                  )}
                  <div className="hint">AR/AP legs in CAD · FX tolerance ±50 or 2%</div>
                </td>
                <td className="num">{money(schedule.ic_mirror.ours.ar, schedule.ic_mirror.currency)}</td>
                <td className="num">{money(schedule.ic_mirror.ours.ap, schedule.ic_mirror.currency)}</td>
                <td className="num">{money(schedule.ic_mirror.theirs_net, schedule.ic_mirror.currency)}</td>
                <td className="num">{money(schedule.ic_mirror.difference, schedule.ic_mirror.currency)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {schedule.kind === 'intercompany' && (
        <div className="table-wrap" style={{ maxHeight: 280 }}>
          <table className="data">
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th>Status</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {(schedule.unmatched || []).map((r) => (
                <tr key={`u-${r.transaction_id}`}>
                  <td>{r.txn_date}</td>
                  <td>
                    {r.description}
                    <div className="hint">{r.entity_code}</div>
                  </td>
                  <td>
                    <span className="badge open">unmatched</span>
                  </td>
                  <td className="num">{money(r.signed_amount, currency)}</td>
                </tr>
              ))}
              {(schedule.matched || []).slice(0, 20).map((r) => (
                <tr key={`m-${r.transaction_id}`}>
                  <td>{r.txn_date}</td>
                  <td>
                    {r.description}
                    <div className="hint">{r.entity_code}</div>
                  </td>
                  <td>
                    <span className="badge ok">matched</span>
                  </td>
                  <td className="num">{money(r.signed_amount, currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {schedule.kind === 'lead' && (
        <div className="table-wrap" style={{ maxHeight: 280 }}>
          <table className="data">
            <thead>
              <tr>
                <th>Account</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {(schedule.accounts || []).map((a) => (
                <tr key={a.account_code}>
                  <td>
                    {a.account_code} {a.account_name}
                  </td>
                  <td className="num">{money(a.total ?? 0, currency)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>vs statement {money(schedule.gl_amount, currency)}</td>
                <td className="num">{money(schedule.schedule_total ?? 0, currency)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </>
  )
}
