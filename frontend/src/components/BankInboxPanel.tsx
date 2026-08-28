import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeftRight, Building2, Inbox, Radio, RefreshCw } from 'lucide-react'
import {
  api,
  type Account,
  type BankAccount,
  type BankFeed,
  type Entity,
  type FxRate,
  type Transaction,
} from '../api'
import { AccountPicker } from './AccountPicker'
import { money } from '../lib/format'

type Props = {
  year: number
  month: number
  entityId: string
  entityCode: string | null
  onChanged?: () => void
  onMessage?: (msg: string) => void
}

function periodBounds(year: number, month: number) {
  const last = new Date(year, month, 0).getDate()
  const mm = String(month).padStart(2, '0')
  return {
    date_from: `${year}-${mm}-01`,
    date_to: `${year}-${mm}-${String(last).padStart(2, '0')}`,
  }
}

function latestRate(rows: FxRate[], from: string, to: string, rateType: string) {
  return rows.find((r) => r.from_currency === from && r.to_currency === to && r.rate_type === rateType)
}

export function BankInboxPanel({ year, month, entityId, entityCode, onChanged, onMessage }: Props) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [entities, setEntities] = useState<Entity[]>([])
  const [banks, setBanks] = useState<BankAccount[]>([])
  const [feeds, setFeeds] = useState<BankFeed[]>([])
  const [fx, setFx] = useState<FxRate[]>([])
  const [rows, setRows] = useState<Transaction[]>([])
  const [rememberRule, setRememberRule] = useState(true)
  const [icEntity, setIcEntity] = useState<Record<number, string>>({})
  const [xferBank, setXferBank] = useState<Record<number, string>>({})
  const [busyId, setBusyId] = useState<number | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const bounds = useMemo(() => periodBounds(year, month), [year, month])

  const loadInbox = useCallback(async () => {
    if (!entityId) return
    const data = await api.transactions({
      entity_id: entityId,
      date_from: bounds.date_from,
      date_to: bounds.date_to,
      uncategorized_only: true,
      limit: 200,
    })
    setRows(data)
  }, [entityId, bounds.date_from, bounds.date_to])

  useEffect(() => {
    Promise.all([api.accounts(), api.entities(), api.bankAccounts(), api.bankFeeds(), api.fxRates()])
      .then(([a, e, b, f, rates]) => {
        setAccounts(a)
        setEntities(e)
        setBanks(b)
        setFeeds(f)
        setFx(rates)
      })
      .catch((err: Error) => setError(err.message))
  }, [])

  useEffect(() => {
    loadInbox().catch((err: Error) => setError(err.message))
  }, [loadInbox])

  const entityBanks = useMemo(
    () => banks.filter((b) => String(b.entity_id) === entityId),
    [banks, entityId],
  )
  const otherEntities = useMemo(
    () => entities.filter((e) => String(e.id) !== entityId),
    [entities, entityId],
  )
  const entityFeeds = useMemo(
    () => feeds.filter((f) => String(f.entity_id) === entityId),
    [feeds, entityId],
  )
  const pendingFeeds = entityFeeds.filter((f) => f.status === 'connected' && f.pending_count > 0)
  const pendingTotal = pendingFeeds.reduce((n, f) => n + f.pending_count, 0)

  const usdCadClose = latestRate(fx, 'USD', 'CAD', 'closing')
  const usdCadAvg = latestRate(fx, 'USD', 'CAD', 'average')

  const afterChange = async (msg: string) => {
    await loadInbox()
    api.bankFeeds().then(setFeeds).catch(() => undefined)
    onChanged?.()
    onMessage?.(msg)
  }

  const run = async (txnId: number, work: () => Promise<unknown>, ok: string) => {
    setBusyId(txnId)
    setError(null)
    try {
      await work()
      await afterChange(ok)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusyId(null)
    }
  }

  const categorize = (txn: Transaction, accountId: number) =>
    run(
      txn.id,
      () => api.categorize(txn.id, { account_id: accountId, create_rule: rememberRule }),
      rememberRule ? 'Categorized · rule remembered' : 'Categorized',
    )

  const markTransfer = (txn: Transaction) => {
    const otherId = xferBank[txn.id] || entityBanks.find((b) => b.id !== txn.bank_account_id)?.id
    return run(
      txn.id,
      () =>
        api.markTransfer(txn.id, {
          create_rule: rememberRule,
          other_bank_account_id: otherId ? Number(otherId) : null,
        }),
      rememberRule ? 'Marked transfer · rule remembered' : 'Marked transfer',
    )
  }

  const markIc = (txn: Transaction) => {
    const counter = icEntity[txn.id] || (otherEntities[0] ? String(otherEntities[0].id) : '')
    if (!counter) {
      setError('Pick the other entity for intercompany')
      return Promise.resolve()
    }
    return run(
      txn.id,
      () =>
        api.markIntercompany(txn.id, {
          counter_entity_id: Number(counter),
          create_rule: rememberRule,
        }),
      rememberRule ? 'Marked intercompany · rule remembered' : 'Marked intercompany',
    )
  }

  const syncFeeds = async () => {
    const connected = entityFeeds.filter((f) => f.status === 'connected')
    if (!connected.length) {
      onMessage?.('Connect a feed on Banks first')
      return
    }
    setSyncing(true)
    setError(null)
    try {
      let imported = 0
      for (const feed of connected) {
        const res = await api.syncFeed(feed.bank_account_id, year, month)
        imported += res.imported
      }
      const next = await api.bankFeeds()
      setFeeds(next)
      await loadInbox()
      onChanged?.()
      onMessage?.(imported ? `Synced ${imported} new item(s)` : 'Feeds already caught up')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  const applyRules = async () => {
    setSyncing(true)
    setError(null)
    try {
      const res = await api.applyRules()
      await loadInbox()
      onChanged?.()
      onMessage?.(`Rules categorized ${res.categorized}`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  if (!entityId) return null

  return (
    <section className="panel bank-inbox">
      <div className="panel-header">
        <h2>
          <Inbox size={16} /> Bank inbox
        </h2>
        <span className="hint">
          {rows.length} uncategorized · {entityCode ?? 'entity'} · {year}-{String(month).padStart(2, '0')}
        </span>
      </div>

      <div className="fx-strip">
        <span>
          USD→CAD closing {usdCadClose ? Number(usdCadClose.rate).toFixed(4) : '—'}
          {usdCadClose ? ` · ${usdCadClose.rate_date}` : ''}
        </span>
        <span>average {usdCadAvg ? Number(usdCadAvg.rate).toFixed(4) : '—'}</span>
        <Link className="btn ghost" to="/settings">
          Rules & FX
        </Link>
      </div>

      <div className="filters" style={{ padding: '0 1rem 0.75rem' }}>
        <label className="btn ghost">
          <input
            type="checkbox"
            checked={rememberRule}
            onChange={(e) => setRememberRule(e.target.checked)}
          />
          Remember as a rule
        </label>
        <button className="btn" type="button" disabled={syncing} onClick={() => void applyRules()}>
          <RefreshCw size={14} /> Apply rules
        </button>
        <button className="btn" type="button" disabled={syncing} onClick={() => void syncFeeds()}>
          <Radio size={14} /> {syncing ? 'Syncing…' : 'Sync feeds'}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {pendingTotal > 0 && (
        <div className="inbox-pending">
          <strong>{pendingTotal} feed item(s) not yet in the book</strong>
          <ul className="feed-pending">
            {pendingFeeds.flatMap((feed) =>
              (feed.pending || []).slice(0, 6).map((item, idx) => (
                <li key={`${feed.id}-${item.external_id || idx}`}>
                  <span>{item.txn_date}</span>
                  <span>
                    {feed.bank_account_name} · {item.description}
                  </span>
                  <span className="num">{money(item.amount, item.currency)}</span>
                </li>
              )),
            )}
          </ul>
        </div>
      )}

      {rows.length === 0 && pendingTotal === 0 ? (
        <p className="hint" style={{ padding: '0 1rem 1rem' }}>
          Inbox is clear for this period. Categorized lines sit on the bank book below.
        </p>
      ) : rows.length === 0 ? (
        <p className="hint" style={{ padding: '0 1rem 1rem' }}>
          Sync the feed to pull pending items into this inbox, then mark Transfer or Intercompany.
        </p>
      ) : (
        <div className="table-wrap" style={{ maxHeight: 420 }}>
          <table className="data">
            <thead>
              <tr>
                <th>Date</th>
                <th>Bank</th>
                <th>Description</th>
                <th className="num">Amount</th>
                <th>Account / Transfer / IC</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((txn) => {
                const otherBanks = entityBanks.filter((b) => b.id !== txn.bank_account_id)
                const defaultIc = icEntity[txn.id] || (otherEntities[0] ? String(otherEntities[0].id) : '')
                const defaultXfer =
                  xferBank[txn.id] || (otherBanks[0] ? String(otherBanks[0].id) : '')
                const locked = txn.is_editable === false
                return (
                  <tr key={txn.id}>
                    <td>{txn.txn_date}</td>
                    <td>{txn.bank_account_name ?? '—'}</td>
                    <td>
                      <div>{txn.description}</div>
                      {txn.counterparty ? <div className="hint">{txn.counterparty}</div> : null}
                    </td>
                    <td className="num">{money(txn.amount, txn.currency)}</td>
                    <td>
                      <div className="inbox-row-actions">
                        <AccountPicker
                          accounts={accounts}
                          disabled={locked || busyId === txn.id}
                          placeholder="GL account…"
                          onSelect={(accountId) => void categorize(txn, accountId)}
                        />
                        {otherBanks.length > 1 && (
                          <select
                            className="select"
                            disabled={locked}
                            value={defaultXfer}
                            onChange={(e) => setXferBank((prev) => ({ ...prev, [txn.id]: e.target.value }))}
                            aria-label="Other bank for transfer"
                          >
                            {otherBanks.map((b) => (
                              <option key={b.id} value={b.id}>
                                {b.name}
                              </option>
                            ))}
                          </select>
                        )}
                        <button
                          className="btn"
                          type="button"
                          disabled={locked || busyId === txn.id}
                          onClick={() => void markTransfer(txn)}
                        >
                          <ArrowLeftRight size={14} /> Transfer
                        </button>
                        {otherEntities.length > 1 && (
                          <select
                            className="select"
                            disabled={locked}
                            value={defaultIc}
                            onChange={(e) => setIcEntity((prev) => ({ ...prev, [txn.id]: e.target.value }))}
                            aria-label="Intercompany entity"
                          >
                            {otherEntities.map((e) => (
                              <option key={e.id} value={e.id}>
                                {e.code}
                              </option>
                            ))}
                          </select>
                        )}
                        <button
                          className="btn"
                          type="button"
                          disabled={locked || busyId === txn.id || !defaultIc}
                          onClick={() => void markIc(txn)}
                        >
                          <Building2 size={14} /> Intercompany
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
