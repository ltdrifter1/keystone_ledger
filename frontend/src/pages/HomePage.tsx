import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, CheckCircle2, FileBarChart2, BookOpen } from 'lucide-react'
import { api, type EngagementHome } from '../api'
import { useEngagement } from '../period/PeriodContext'

export function HomePage() {
  const { year, month, label, entityId, entityCode, entityName, setPeriod } = useEngagement()
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

  if (!entityId) return <p className="hint">Loading entity…</p>
  if (error) return <div className="error">{error}</div>
  if (loading || !home) return <p className="hint">Loading pack…</p>

  const p = home.progress
  const printable = Boolean(p.can_print)
  const plugs = home.queue.filter((q) => q.status !== 'ok')

  return (
    <div className="home-engagement">
      <div className="page-header">
        <div>
          <h1>
            {entityName ?? entityCode ?? 'Entity'} · {label}
          </h1>
          <p>
            Exceptions that stop this pack from printing. CAN and USA stay separate — this is not a
            consolidation.
          </p>
        </div>
        <div className="toolbar">
          <Link className="btn primary" to={home.statements_href}>
            <FileBarChart2 size={14} /> Statements
          </Link>
          <Link className="btn" to={home.work_href}>
            <BookOpen size={14} /> Books
          </Link>
        </div>
      </div>

      <div className="home-status-bar" aria-label="Pack status">
        <span>
          Pack <strong>{printable ? 'printable' : 'blocked'}</strong>
        </span>
        <span className="home-status-sep" />
        <span>
          Balance sheet <strong>{p.statements_balanced ? 'in balance' : 'out of balance'}</strong>
        </span>
        <span className="home-status-sep" />
        <span>
          Uncategorized <strong>{p.uncategorized}</strong>
        </span>
      </div>

      <section className={`panel home-primary ${printable ? 'ok' : 'warn'}`}>
        <div>
          <div className="hint">{printable ? 'Ready' : `${plugs.length} exception${plugs.length === 1 ? '' : 's'}`}</div>
          <h2>{printable ? 'Pack is printable' : 'Statement will not print'}</h2>
          <p className="hint">
            {printable
              ? 'P&L, balance sheet, equity, and trial balance are ready for this entity.'
              : 'Fix the items below. Do not issue this pack until they are gone.'}
          </p>
        </div>
        <Link className="btn primary" to={home.statements_href}>
          {printable ? (
            <>
              <CheckCircle2 size={14} /> Open statements
            </>
          ) : (
            <>
              Open statements <ArrowRight size={14} />
            </>
          )}
        </Link>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Exceptions</h2>
          <span className="hint">Why the pack will not print</span>
        </div>
        {printable && plugs.length === 0 ? (
          <p className="hint" style={{ padding: '0.85rem 1rem' }}>
            None. Print or export from Statements.
          </p>
        ) : (
          <ol className="home-queue">
            {plugs.map((item) => (
              <li key={item.key} className={`home-queue-item ${item.status}`}>
                <div className="home-queue-step">{item.step}</div>
                <div className="home-queue-body">
                  <strong>{item.title}</strong>
                  <span className="hint">{item.detail}</span>
                </div>
                <Link className="btn ghost" to={item.href}>
                  Open <ArrowRight size={14} />
                </Link>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}
