import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Link2, Link2Off, RefreshCw, Radio } from 'lucide-react'
import { api, type BankFeed, type Entity } from '../api'
import { money } from '../lib/format'
import { useEngagement } from '../period/PeriodContext'
import { useToast } from '../hooks/useToast'

function relativeTime(iso?: string | null) {
  if (!iso) return 'Never synced'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'Never synced'
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000))
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 36) return `${hours}h ago`
  return new Date(iso).toLocaleString()
}

export function BankAccountsPage() {
  const { entityId, entityCode, year, month } = useEngagement()
  const [feeds, setFeeds] = useState<BankFeed[]>([])
  const [entities, setEntities] = useState<Entity[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const { toast, show } = useToast()

  const load = async () => {
    const [f, e] = await Promise.all([api.bankFeeds(), api.entities()])
    setFeeds(f)
    setEntities(e)
  }

  useEffect(() => {
    load().catch((err: Error) => setError(err.message))
  }, [])

  const scoped = useMemo(() => {
    if (!entityId) return feeds
    return feeds.filter((f) => String(f.entity_id) === entityId)
  }, [feeds, entityId])

  const run = async (bankId: number, fn: () => Promise<unknown>, ok: string) => {
    setBusy(bankId)
    setError(null)
    try {
      await fn()
      await load()
      show(ok)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const connected = scoped.filter((f) => f.status === 'connected').length
  const pending = scoped.reduce((n, f) => n + (f.status === 'connected' ? f.pending_count : 0), 0)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Banks</h1>
          <p>
            Live Open Banking feeds for {entityCode ?? 'this entity'}. Sync pulls new items and the
            statement ending balance — no CSV required.
          </p>
        </div>
        <div className="toolbar">
          <span className="badge ok">
            <Radio size={12} /> {connected}/{scoped.length} live · {pending} pending
          </span>
          <Link className="btn" to={`/work?year=${year}&month=${month}`}>
            Work desk
          </Link>
        </div>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="feed-grid">
        {scoped.map((f) => (
          <section key={f.bank_account_id} className={`panel feed-card ${f.status}`}>
            <div className="panel-header">
              <div>
                <h2>{f.bank_account_name}</h2>
                <span className="hint">
                  {f.institution ?? 'Bank'} · {f.account_number} · {f.currency}
                </span>
              </div>
              <span className={`badge ${f.status === 'connected' ? 'ok' : 'open'}`}>
                {f.status === 'connected' ? (f.is_stale ? 'stale' : 'live') : 'disconnected'}
              </span>
            </div>
            <div className="feed-meta">
              <div>
                <div className="kpi-label">Live balance</div>
                <div className="kpi-value" style={{ fontSize: '1.1rem' }}>
                  {f.last_balance == null ? '—' : money(f.last_balance, f.currency)}
                </div>
                <div className="hint">
                  {f.last_balance_as_of ? `as of ${f.last_balance_as_of}` : 'Sync to refresh'}
                </div>
              </div>
              <div>
                <div className="kpi-label">Last sync</div>
                <div>{relativeTime(f.last_synced_at)}</div>
                <div className="hint">
                  {f.pending_count > 0 ? `${f.pending_count} new item(s)` : 'Caught up'}
                </div>
              </div>
            </div>
            {f.pending.length > 0 && (
              <ul className="feed-pending">
                {f.pending.slice(0, 4).map((p) => (
                  <li key={p.external_id ?? p.description}>
                    <span>{p.txn_date}</span>
                    <span>{p.description.replace('WBC LIVE — ', '')}</span>
                    <span className="num">{money(p.amount, p.currency)}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="toolbar" style={{ padding: '0 1rem 1rem' }}>
              {f.status !== 'connected' ? (
                <button
                  className="btn primary"
                  disabled={busy === f.bank_account_id}
                  onClick={() =>
                    void run(f.bank_account_id, () => api.connectFeed(f.bank_account_id), 'Feed connected')
                  }
                >
                  <Link2 size={14} /> Connect feed
                </button>
              ) : (
                <>
                  <button
                    className="btn primary"
                    disabled={busy === f.bank_account_id}
                    onClick={() =>
                      void run(
                        f.bank_account_id,
                        () => api.syncFeed(f.bank_account_id, year, month),
                        'Feed synced',
                      )
                    }
                  >
                    <RefreshCw size={14} /> {busy === f.bank_account_id ? 'Syncing…' : 'Sync now'}
                  </button>
                  <Link
                    className="btn"
                    to={`/work?year=${year}&month=${month}&bank=${f.bank_account_id}`}
                  >
                    Close from feed
                  </Link>
                  <button
                    className="btn ghost"
                    disabled={busy === f.bank_account_id}
                    onClick={() =>
                      void run(
                        f.bank_account_id,
                        () => api.disconnectFeed(f.bank_account_id),
                        'Feed disconnected',
                      )
                    }
                  >
                    <Link2Off size={14} /> Disconnect
                  </button>
                </>
              )}
            </div>
          </section>
        ))}
      </div>
      {entities.length === 0 && <p className="hint">Loading…</p>}
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
