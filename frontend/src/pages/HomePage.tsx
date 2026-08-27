import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, CheckCircle2, ClipboardList, FileBarChart2, Sparkles } from 'lucide-react'
import { api, type EngagementHome } from '../api'
import { useEngagement } from '../period/PeriodContext'

export function HomePage() {
  const { year, month, label, entityId, entityCode, setPeriod } = useEngagement()
  const [searchParams] = useSearchParams()
  const [home, setHome] = useState<EngagementHome | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

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

  if (!entityId) return <p className="hint">Loading engagement context…</p>
  if (error) return <div className="error">{error}</div>
  if (loading || !home) return <p className="hint">Loading engagement…</p>

  const p = home.progress
  const next = home.queue[0]
  const done = next?.status === 'ok'
  const openCount = home.queue.filter((q) => q.status !== 'ok').length

  return (
    <div className="home-engagement">
      <div className="page-header">
        <div>
          <h1>
            {entityCode ?? 'Entity'} · {label}
          </h1>
          <p>Work the queue top-down. Then binder sign-off, then statements.</p>
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
        </div>
      </div>

      <div className="home-status-bar" aria-label="Engagement progress">
        <span>
          Banks <strong>{p.banks_locked}/{p.banks_total}</strong> locked
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
          Binder <strong>{p.binder_reviewed}/{p.binder_total}</strong>
        </span>
        <span className="home-status-sep" />
        <span>
          Cash WP <strong>{p.cash_ready ? 'ready' : 'open'}</strong>
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
        </section>
      )}

      <section className="panel">
        <div className="panel-header">
          <h2>Engagement queue</h2>
          <span className="hint">Ordered: Work → Binder → Statements</span>
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
              <Link className="btn ghost" to={item.href}>
                Open <ArrowRight size={14} />
              </Link>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
