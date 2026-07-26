import { Link } from 'react-router-dom'
import { X, ExternalLink, CheckCircle2, AlertTriangle, ClipboardList } from 'lucide-react'
import type { DrillOut } from '../api'
import { money } from '../lib/format'
import { usePeriod } from '../period/PeriodContext'

type Props = {
  open: boolean
  loading?: boolean
  error?: string | null
  data: DrillOut | null
  onClose: () => void
}

export function WorkingPaperDrawer({ open, loading, error, data, onClose }: Props) {
  const { year, month } = usePeriod()
  const template = data?.template ?? null
  const binderHref = template
    ? `/working-papers?year=${year}&month=${month}&key=${template.key}`
    : `/working-papers?year=${year}&month=${month}`

  return (
    <>
      <div className={`wp-scrim ${open ? 'open' : ''}`} onClick={onClose} />
      <aside className={`wp-drawer ${open ? 'open' : ''}`} aria-hidden={!open}>
        <div className="wp-sheet">
          <header className="wp-header">
            <div>
              <div className="wp-kicker">Working paper</div>
              <h2>
                {data?.wp_ref && <span className="wp-ref">{data.wp_ref}</span>}
                {data?.line_label ?? (loading ? 'Loading…' : 'Detail')}
              </h2>
              <p className="wp-meta">
                {data ? (
                  <>
                    {data.period_label} · {data.currency} · {data.row_count} supporting item
                    {data.row_count === 1 ? '' : 's'}
                  </>
                ) : (
                  'Select a statement line to open the supporting schedule.'
                )}
              </p>
            </div>
            <button className="btn ghost wp-close" onClick={onClose} aria-label="Close working paper">
              <X size={16} />
            </button>
          </header>

          {error && <div className="error" style={{ margin: '0 1.1rem 0.75rem' }}>{error}</div>}
          {loading && <p className="hint" style={{ padding: '0 1.1rem' }}>Assembling supporting detail…</p>}

          {data && !loading && (
            <>
              <div className="wp-tie">
                <div className="wp-tie-cell">
                  <span>Statement</span>
                  <strong>{money(data.statement_amount, data.currency)}</strong>
                </div>
                <div className="wp-tie-cell">
                  <span>Detail total</span>
                  <strong>{money(data.detail_total, data.currency)}</strong>
                </div>
                <div className={`wp-tie-cell ${data.is_tied ? 'tied' : 'untied'}`}>
                  <span>{data.is_tied ? 'Tied' : 'Difference'}</span>
                  <strong>
                    {data.is_tied ? (
                      <>
                        <CheckCircle2 size={14} /> Balanced
                      </>
                    ) : (
                      <>
                        <AlertTriangle size={14} /> {money(data.difference, data.currency)}
                      </>
                    )}
                  </strong>
                </div>
              </div>

              {template && (
                <div className="wp-template-block">
                  <div className="wp-template-head">
                    <ClipboardList size={14} />
                    <strong>{template.title} · binder</strong>
                    <Link className="btn ghost" to={binderHref}>
                      Open binder doc <ExternalLink size={12} />
                    </Link>
                  </div>
                  <p className="wp-template-purpose">{template.purpose}</p>
                  <p className="hint wp-template-tie">
                    <strong>Tie-out:</strong> {template.tie_out}
                  </p>
                  <p className="hint" style={{ margin: '0.35rem 0 0' }}>
                    Procedures, P/R sign-off, and period schedule live in the binder for {year}-
                    {String(month).padStart(2, '0')}.
                  </p>
                </div>
              )}

              <div className="wp-toolbar">
                <span className="hint">Source transactions for this line</span>
                <Link
                  className="btn ghost"
                  to={`/transactions?search=${encodeURIComponent(data.line_label.split(' ')[0] || '')}`}
                >
                  Open ledger <ExternalLink size={14} />
                </Link>
              </div>

              <div className="wp-table-wrap">
                <table className="data wp-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Entity</th>
                      <th>Description</th>
                      <th>Account</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.lines.length === 0 && (
                      <tr>
                        <td colSpan={5} className="hint">
                          No supporting transactions in this period.
                        </td>
                      </tr>
                    )}
                    {data.lines.map((row, idx) => (
                      <tr key={`${row.transaction_id}-${row.account_id}-${idx}`}>
                        <td>{row.txn_date}</td>
                        <td>
                          <span className="badge">{row.entity_code ?? row.entity_id}</span>
                        </td>
                        <td className="desc-cell">
                          <div>{row.description}</div>
                          <div className="hint">
                            {row.bank_account_name ?? '—'}
                            {row.is_split && ' · split'}
                            {row.is_reconciled && ' · recon'}
                            {row.split_memo ? ` · ${row.split_memo}` : ''}
                          </div>
                        </td>
                        <td>
                          <span className="wp-acct">
                            {row.account_code} {row.account_name}
                          </span>
                        </td>
                        <td className="num">{money(row.signed_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={4}>Supporting total</td>
                      <td className="num">{money(data.detail_total)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  )
}
