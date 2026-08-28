import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type ReportFilters, type TrialBalance } from '../api'
import { money } from '../lib/format'
import { useEngagement } from '../period/PeriodContext'

function periodEndIso(year: number, month: number) {
  const d = new Date(year, month, 0)
  return d.toISOString().slice(0, 10)
}

export function TrialBalancePage() {
  const { year, month, entityId, entityCode, entityName, entityCurrency } = useEngagement()
  const [tb, setTb] = useState<TrialBalance | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const filters: ReportFilters = useMemo(
    () => ({
      report_type: 'trial_balance',
      period: 'monthly',
      year,
      month,
      scenario_id: 1,
      reporting_currency: entityCurrency || 'CAD',
      consolidate: false,
      entity_ids: entityId ? [Number(entityId)] : null,
      as_of_date: periodEndIso(year, month),
      date_to: periodEndIso(year, month),
    }),
    [year, month, entityId, entityCurrency],
  )

  const run = useCallback(async () => {
    if (!entityId) {
      setError('Select one entity. This pack does not consolidate CAN and USA.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      setTb(await api.trialBalance(filters))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [filters, entityId])

  useEffect(() => {
    void run()
  }, [run])

  const nz = (v?: string | number | null) => Number(v || 0) !== 0

  return (
    <div className="report-workspace">
      <div className="page-header statement-cover-header">
        <div>
          <p className="statement-kicker">{entityCode ?? 'Entity'}</p>
          <h1 className="statement-cover">
            {tb?.cover_title ||
              `${entityName ?? entityCode ?? 'Entity'} · Trial Balance · ${tb?.period_label ?? ''} · ${entityCurrency || 'CAD'}`}
          </h1>
          <p className="print-hide">
            Double-entry trial balance. Uncategorized bank lines post to 9999 suspense. Debits must equal credits.
          </p>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {tb && tb.is_balanced != null && (
        <div className={`banner ${tb.is_balanced ? 'ok' : 'warn'}`}>
          {tb.is_balanced
            ? `In balance · Debits = Credits (${tb.currency})`
            : `Out of balance by ${money(tb.balance_difference, tb.currency)}`}
        </div>
      )}

      {tb && !tb.is_complete && (
        <div className="banner warn">
          Trial balance is not complete
          {tb.unmapped_count ? ` · ${tb.unmapped_count} unmapped account(s)` : ''}
          {tb.uncategorized_count ? ` · ${tb.uncategorized_count} uncategorized item(s)` : ''}
        </div>
      )}
      {tb?.is_complete && <div className="banner ok">Mapped, balanced, and complete</div>}

      <section className="panel statement-panel">
        <div className="panel-header print-hide">
          <h2>{tb?.title ?? 'Trial Balance'}</h2>
          <span className="hint">{loading ? 'Running…' : tb?.accounting_basis ?? ''}</span>
        </div>
        <div className="table-wrap statement-wrap">
          <table className="data statement-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Account</th>
                <th className="num">Opening Dr</th>
                <th className="num">Opening Cr</th>
                <th className="num">Period Dr</th>
                <th className="num">Period Cr</th>
                <th className="num">Closing Dr</th>
                <th className="num">Closing Cr</th>
                <th>Mapped line</th>
                <th>Exception</th>
              </tr>
            </thead>
            <tbody>
              {tb?.rows.map((row) => (
                <tr key={`${row.account_code}-${row.account_id ?? 's'}`} className={row.exception ? 'tb-exception' : ''}>
                  <td>{row.account_code}</td>
                  <td>{row.account_name}</td>
                  <td className="num">{nz(row.opening_debit) ? money(row.opening_debit) : '—'}</td>
                  <td className="num">{nz(row.opening_credit) ? money(row.opening_credit) : '—'}</td>
                  <td className="num">{nz(row.period_debit) ? money(row.period_debit) : '—'}</td>
                  <td className="num">{nz(row.period_credit) ? money(row.period_credit) : '—'}</td>
                  <td className="num">{nz(row.debit) ? money(row.debit) : '—'}</td>
                  <td className="num">{nz(row.credit) ? money(row.credit) : '—'}</td>
                  <td>{row.line_label || '—'}</td>
                  <td className="hint">{row.exception || ''}</td>
                </tr>
              ))}
              {tb && (
                <tr className="total">
                  <td />
                  <td>Total</td>
                  <td colSpan={4} />
                  <td className="num">{money(tb.total_debit, tb.currency)}</td>
                  <td className="num">{money(tb.total_credit, tb.currency)}</td>
                  <td colSpan={2} />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {tb?.notes && tb.notes.length > 0 && (
        <section className="panel statement-notes">
          <div className="panel-header">
            <h2>Notes</h2>
          </div>
          <ol className="notes-list">
            {tb.notes.map((note) => (
              <li key={note.heading}>
                <strong>{note.heading}.</strong> {note.body}
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}
