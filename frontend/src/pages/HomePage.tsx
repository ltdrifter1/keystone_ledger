import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, CheckCircle2, ClipboardList, FileBarChart2, Lock, Sparkles } from 'lucide-react'
import { api, type EngagementHome } from '../api'
import { useEngagement } from '../period/PeriodContext'

export function HomePage() {
  const { year, month, label, entityId, entityCode, entityName, setPeriod } = useEngagement()
  const [searchParams] = useSearchParams()
  const [home, setHome] = useState<EngagementHome | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [locking, setLocking] = useState(false)

  useEffect(() => {
    const y = searchParams.get('year')
    const m = searchParams.get('month')
    if (y && m) {
      const yi = Number(y)
      const mi = Number(m)
      if (yi && mi && (yi !== year || mi !== month)) setPeriod(yi, mi)
    }
  }, [searchParams, year, month, setPeriod])

  const load = useCallback(async () => {
    if (!entityId) return
    setLoading(true)
    setError(null)
    try {
      setHome(await api.engagementHome({ year, month, entity_id: Number(entityId) }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [year, month, entityId])

  useEffect(() => {
    void load()
  }, [load])

  const lockMonth = async () => {
    if (!entityId) return
    setLocking(true)
    setError(null)
    try {
      await api.lockEntityMonth(Number(entityId), year, month)
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLocking(false)
    }
  }

  if (!entityId) return <p className="hint">Loading engagement context…</p>
  if (error) return <div className="error">{error}</div>
  if (loading || !home) return <p className="hint">Loading engagement…</p>

  const p = home.progress
  const next = home.queue[0]
  const done = next?.status === 'ok'
  const openCount = home.queue.filter((q) => q.status !== 'ok').length
  const journalLed = Boolean(home.journal_led || p.journal_led)
  const monthLocked = Boolean(home.month_lock?.is_locked || p.month_locked)

  const actionFor = (item: (typeof home.queue)[0]) => {
    if (item.key === 'lock-month') {
      return (
        <button className="btn primary" type="button" disabled={locking || monthLocked} onClick={() => void lockMonth()}>
          <Lock size={14} /> {locking ? 'Locking…' : monthLocked ? 'Month locked' : 'Lock month'}
        </button>
      )
    }
    return (
      <Link className="btn ghost" to={item.href}>
        Open <ArrowRight size={14} />
      </Link>
    )
  }

  return (
    <div className="home-engagement">
      <div className="page-header">
        <div>
          <h1>
            {entityName ?? entityCode ?? 'Entity'} · {label}
          </h1>
          <p>
            Monthly rec for {entityName ?? entityCode ?? 'this company'} — Work the queue top-down. This version is
            month-end close, not a daily inbox. WBC CAN and WBC USA stay separate.
          </p>
        </div>
        <div className="toolbar">
          <Link className="btn" to={home.work_href}>
            <Sparkles size={14} /> Work
          </Link>
          <Link className="btn" to={home.binder_href}>
            <ClipboardList size={14} /> Binder
          </Link>
          <Link className="btn" to={home.statements_href}>
            <FileBarChart2 size={14} /> Statements
          </Link>
          <button className="btn primary" type="button" disabled={locking || monthLocked} onClick={() => void lockMonth()}>
            <Lock size={14} /> {monthLocked ? 'Month locked' : 'Lock month'}
          </button>
        </div>
      </div>

      <div className="home-status-bar" aria-label="Monthly rec progress">
        {journalLed ? (
          <>
            <span>
              Journals <strong>{p.journals ?? 0}</strong>
            </span>
            <span className="home-status-sep" />
            <span>
              Unmatched IC <strong>{p.unmatched_ic ?? 0}</strong>
            </span>
            <span className="home-status-sep" />
            <span>
              Month <strong>{monthLocked ? 'locked' : 'open'}</strong>
            </span>
          </>
        ) : (
          <>
            <span>
              Banks <strong>
                {p.banks_locked}/{p.banks_total}
              </strong>{' '}
              locked
            </span>
            <span className="home-status-sep" />
            <span>
              Blocking <strong>{p.blocking_total}</strong>
            </span>
            <span className="home-status-sep" />
            <span>
              Uncategorized <strong>{p.uncategorized}</strong>
            </span>
            <span className="home-status-sep" />
            <span>
              Unmatched IC <strong>{p.unmatched_ic ?? 0}</strong>
            </span>
            <span className="home-status-sep" />
            <span>
              Month <strong>{monthLocked ? 'locked' : 'open'}</strong>
            </span>
          </>
        )}
        <span className="home-status-sep" />
        <span>
          Binder <strong>
            {p.binder_reviewed}/{p.binder_total}
          </strong>
        </span>
        <span className="home-status-sep" />
        <span>
          Cash WP <strong>{p.cash_ready ? (journalLed ? 'N/A' : 'ready') : 'open'}</strong>
        </span>
      </div>

      {next && (
        <section className={`panel home-primary ${done ? 'ok' : 'warn'}`}>
          <div>
            <div className="hint">
              Next up · step {next.step}
              {!done && openCount > 1 ? ` · ${openCount} open` : ''}
            </div>
            <h2>{next.title}</h2>
            <p className="hint">{next.detail}</p>
          </div>
          {next.key === 'lock-month' ? (
            <button className="btn primary" type="button" disabled={locking || monthLocked} onClick={() => void lockMonth()}>
              <Lock size={14} /> {locking ? 'Locking…' : 'Lock month'}
            </button>
          ) : (
            <Link className="btn primary" to={next.href}>
              {done ? (
                <>
                  <CheckCircle2 size={14} /> Review statements
                </>
              ) : (
                <>
                  Continue <ArrowRight size={14} />
                </>
              )}
            </Link>
          )}
        </section>
      )}

      <section className="panel">
        <div className="panel-header">
          <h2>Monthly rec queue</h2>
          <span className="hint">Ordered: Work → Binder → Lock month → Statements</span>
        </div>
        <ol className="home-queue">
          {home.queue.map((item) => (
            <li key={item.key} className={`home-queue-item ${item.status}`}>
              <div className="home-queue-step">{item.step}</div>
              <div className="home-queue-body">
                <div className="home-queue-meta">
                  <span className={`badge ${item.phase === 'work' ? 'open' : item.phase === 'binder' ? '' : 'ok'}`}>
                    {item.phase}
                  </span>
                  {item.count != null && <span className="hint">{item.count}</span>}
                </div>
                <strong>{item.title}</strong>
                <span className="hint">{item.detail}</span>
              </div>
              {actionFor(item)}
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
