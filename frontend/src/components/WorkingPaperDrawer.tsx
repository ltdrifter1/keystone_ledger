import { Link } from 'react-router-dom'
import { X, ExternalLink, CheckCircle2, AlertTriangle } from 'lucide-react'
import type { DrillOut } from '../api'
import { money } from '../lib/format'

type Props = {
  open: boolean
  loading?: boolean
  error?: string | null
  data: DrillOut | null
  onClose: () => void
}

export function WorkingPaperDrawer({ open, loading, error, data, onClose }: Props) {
  return (
    <>
      <div className={`wp-scrim ${open ? 'open' : ''}`} onClick={onClose} />
      <aside className={`wp-drawer ${open ? 'open' : ''}`} aria-hidden={!open}>
        <div className="wp-sheet">
          <header className="wp-header">
            <div>
              <div className="wp-kicker">Source</div>
              <h2>{data?.line_label ?? (loading ? 'Loading…' : 'Detail')}</h2>
              <p className="wp-meta">
                {data ? (
                  <>
                    {data.period_label} · {data.currency} · {data.row_count} item
                    {data.row_count === 1 ? '' : 's'}
                  </>
                ) : (
                  'Select a statement line to see the underlying transactions.'
                )}
              </p>
            </div>
            <button className="btn ghost wp-close" onClick={onClose} aria-label="Close source detail">
              <X size={16} />
            </button>
          </header>

          {error && <div className="error" style={{ margin: '0 1.1rem 0.75rem' }}>{error}</div>}
          {loading && <p className="hint" style={{ padding: '0 1.1rem' }}>Loading source transactions…</p>}

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

              <div className="wp-toolbar">
                <span className="hint">Transactions behind this line</span>
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
