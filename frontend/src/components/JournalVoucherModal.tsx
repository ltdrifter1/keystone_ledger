import { useEffect, useMemo, useState } from 'react'
import { api, type Account } from '../api'
import { useEngagement } from '../period/PeriodContext'
import { useSession } from '../session/SessionContext'
import { money } from '../lib/format'

type Line = { account_id: string; debit: string; credit: string; memo: string }

const blankLines = (): Line[] => [
  { account_id: '', debit: '', credit: '', memo: '' },
  { account_id: '', debit: '', credit: '', memo: '' },
]

export function JournalVoucherModal({
  accounts,
  open,
  onClose,
  onPosted,
  workingPaperKey,
  sourceTransactionId,
  defaultDescription,
}: {
  accounts: Account[]
  open: boolean
  onClose: () => void
  onPosted: () => void
  workingPaperKey?: string
  sourceTransactionId?: number
  defaultDescription?: string
}) {
  const { year, month, entityId } = useEngagement()
  const { user } = useSession()
  const periodEnd = useMemo(() => new Date(year, month, 0).toISOString().slice(0, 10), [year, month])
  const [txnDate, setTxnDate] = useState(periodEnd)
  const [description, setDescription] = useState(defaultDescription || 'Adjusting journal')
  const [lines, setLines] = useState<Line[]>(blankLines)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setTxnDate(periodEnd)
    setDescription(defaultDescription || 'Adjusting journal')
    setLines(blankLines())
    setError(null)
    setSaving(false)
  }, [open, periodEnd, defaultDescription])

  if (!open) return null

  const debitTotal = lines.reduce((s, l) => s + Number(l.debit || 0), 0)
  const creditTotal = lines.reduce((s, l) => s + Number(l.credit || 0), 0)
  const balanced = Math.abs(debitTotal - creditTotal) < 0.005 && debitTotal > 0

  const post = async () => {
    if (!entityId) {
      setError('Pick an engagement entity first')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await api.postJournal({
        txn_date: txnDate,
        entity_id: Number(entityId),
        description,
        working_paper_key: workingPaperKey,
        source_transaction_id: sourceTransactionId,
        lines: lines
          .filter((l) => l.account_id && (l.debit || l.credit))
          .map((l) => ({
            account_id: Number(l.account_id),
            debit: l.debit || 0,
            credit: l.credit || 0,
            memo: l.memo || undefined,
          })),
      })
      onPosted()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal wide" onClick={(e) => e.stopPropagation()} role="dialog" aria-labelledby="journal-title">
        <h3 id="journal-title">Adjusting journal</h3>
        <p className="hint">
          GL-only voucher · does not hit a bank recon · posted as {user?.initials ?? 'you'}. Debits must equal credits.
        </p>
        {error && <div className="error">{error}</div>}
        <div className="form-row">
          <label>
            Date
            <input className="input" type="date" value={txnDate} onChange={(e) => setTxnDate(e.target.value)} />
          </label>
        </div>
        <div className="form-row">
          <label>
            Description
            <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>Account</th>
              <th className="num">Debit</th>
              <th className="num">Credit</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, idx) => (
              <tr key={idx}>
                <td>
                  <select
                    className="select"
                    value={line.account_id}
                    onChange={(e) => {
                      const next = [...lines]
                      next[idx] = { ...next[idx], account_id: e.target.value }
                      setLines(next)
                    }}
                  >
                    <option value="">Account…</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.code} {a.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    className="input num"
                    inputMode="decimal"
                    value={line.debit}
                    onChange={(e) => {
                      const next = [...lines]
                      next[idx] = { ...next[idx], debit: e.target.value, credit: e.target.value ? '' : next[idx].credit }
                      setLines(next)
                    }}
                  />
                </td>
                <td>
                  <input
                    className="input num"
                    inputMode="decimal"
                    value={line.credit}
                    onChange={(e) => {
                      const next = [...lines]
                      next[idx] = { ...next[idx], credit: e.target.value, debit: e.target.value ? '' : next[idx].debit }
                      setLines(next)
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => setLines([...lines, { account_id: '', debit: '', credit: '', memo: '' }])}
                >
                  Add line
                </button>
              </td>
              <td className="num">{money(debitTotal)}</td>
              <td className="num">{money(creditTotal)}</td>
            </tr>
          </tfoot>
        </table>
        <p className={`hint ${balanced ? '' : 'warn-text'}`}>{balanced ? 'Balanced' : 'Out of balance'}</p>
        <div className="toolbar" style={{ justifyContent: 'flex-end', marginTop: '0.75rem' }}>
          <button className="btn ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" type="button" disabled={!balanced || saving} onClick={() => void post()}>
            {saving ? 'Posting…' : 'Post journal'}
          </button>
        </div>
      </div>
    </div>
  )
}
