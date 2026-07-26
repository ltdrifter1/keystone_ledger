import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ClipboardList, ExternalLink } from 'lucide-react'
import { api, type WorkingPaperTemplate } from '../api'

const SECTION_LABEL: Record<string, string> = {
  asset: 'Assets',
  liability: 'Liabilities',
  equity: 'Equity',
  pnl: 'P&L',
}

function checklistStorageKey(templateKey: string) {
  return `keystone.wp.checklist.${templateKey}`
}

export function WorkingPapersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [templates, setTemplates] = useState<WorkingPaperTemplate[]>([])
  const [activeKey, setActiveKey] = useState<string | null>(searchParams.get('key'))
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [error, setError] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [preparer, setPreparer] = useState('')
  const [reviewer, setReviewer] = useState('')

  useEffect(() => {
    api
      .workingPapers()
      .then((res) => {
        setTemplates(res.templates)
        const fromUrl = searchParams.get('key')
        if (fromUrl && res.templates.some((t) => t.key === fromUrl)) {
          setActiveKey(fromUrl)
        } else if (res.templates.length && !activeKey) {
          setActiveKey(res.templates[0].key)
        }
      })
      .catch((e) => setError((e as Error).message))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once; URL key applied below
  }, [])

  useEffect(() => {
    const fromUrl = searchParams.get('key')
    if (fromUrl && templates.some((t) => t.key === fromUrl)) {
      setActiveKey(fromUrl)
    }
  }, [searchParams, templates])

  const active = useMemo(
    () => templates.find((t) => t.key === activeKey) ?? null,
    [templates, activeKey],
  )

  useEffect(() => {
    if (!active) return
    try {
      const raw = localStorage.getItem(checklistStorageKey(active.key))
      if (!raw) {
        setChecked({})
        setNotes('')
        setPreparer('')
        setReviewer('')
        return
      }
      const parsed = JSON.parse(raw) as {
        checked?: number[]
        notes?: string
        preparer?: string
        reviewer?: string
      }
      const map: Record<string, boolean> = {}
      ;(parsed.checked ?? []).forEach((idx) => {
        map[String(idx)] = true
      })
      setChecked(map)
      setNotes(parsed.notes ?? '')
      setPreparer(parsed.preparer ?? '')
      setReviewer(parsed.reviewer ?? '')
    } catch {
      setChecked({})
    }
  }, [active])

  const persist = (nextChecked: Record<string, boolean>, nextNotes: string, nextPrep: string, nextRev: string) => {
    if (!active) return
    const idxs = Object.entries(nextChecked)
      .filter(([, v]) => v)
      .map(([k]) => Number(k))
    localStorage.setItem(
      checklistStorageKey(active.key),
      JSON.stringify({
        checked: idxs,
        notes: nextNotes,
        preparer: nextPrep,
        reviewer: nextRev,
      }),
    )
  }

  const toggle = (idx: number) => {
    const next = { ...checked, [String(idx)]: !checked[String(idx)] }
    setChecked(next)
    persist(next, notes, preparer, reviewer)
  }

  const doneCount = active
    ? active.procedures.filter((_, i) => checked[String(i)]).length
    : 0

  const reportTypeFor = (tmpl: WorkingPaperTemplate) =>
    tmpl.statement === 'income_statement' ? 'income_statement' : 'balance_sheet'

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Working papers</h1>
          <p>
            Basic templates for each main section — procedures, evidence, and tie-out. Checklist progress is
            saved in this browser.
          </p>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="wp-pack-layout">
        <section className="panel">
          <div className="panel-header">
            <h2>
              <ClipboardList size={16} /> Index
            </h2>
            <span className="hint">{templates.length} sections</span>
          </div>
          <div className="wp-index">
            {templates.map((tmpl) => (
              <button
                key={tmpl.key}
                type="button"
                className={`wp-index-row ${activeKey === tmpl.key ? 'active' : ''}`}
                onClick={() => {
                  setActiveKey(tmpl.key)
                  setSearchParams({ key: tmpl.key })
                }}
              >
                <span className="wp-ref">{tmpl.wp_ref}</span>
                <span className="wp-index-title">
                  <strong>{tmpl.title}</strong>
                  <span className="hint">{SECTION_LABEL[tmpl.section] ?? tmpl.section}</span>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="panel wp-pack-detail">
          {!active && <p className="hint" style={{ padding: '1rem' }}>Select a section template.</p>}
          {active && (
            <>
              <div className="panel-header">
                <h2>
                  <span className="wp-ref">{active.wp_ref}</span> {active.title}
                </h2>
                <Link className="btn ghost" to={`/reports?type=${reportTypeFor(active)}`}>
                  Open statement <ExternalLink size={14} />
                </Link>
              </div>

              <div className="wp-pack-body">
                <div className="wp-pack-meta">
                  <div>
                    <span>Purpose</span>
                    <p>{active.purpose}</p>
                  </div>
                  <div>
                    <span>Objective</span>
                    <p>{active.objective}</p>
                  </div>
                  <div>
                    <span>Tie-out</span>
                    <p className="wp-tieout">{active.tie_out}</p>
                  </div>
                </div>

                <div className="wp-pack-grid">
                  <div>
                    <div className="wp-pack-section-head">
                      <h3>Procedures</h3>
                      <span className="hint">
                        {doneCount}/{active.procedures.length} done
                      </span>
                    </div>
                    <ol className="wp-procedure-list">
                      {active.procedures.map((step, idx) => (
                        <li key={idx} className={checked[String(idx)] ? 'done' : ''}>
                          <label>
                            <input
                              type="checkbox"
                              checked={!!checked[String(idx)]}
                              onChange={() => toggle(idx)}
                            />
                            <span>{step}</span>
                          </label>
                        </li>
                      ))}
                    </ol>
                  </div>

                  <div>
                    <div className="wp-pack-section-head">
                      <h3>Evidence</h3>
                    </div>
                    <ul className="wp-evidence-list">
                      {active.evidence.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>

                    <div className="wp-pack-section-head" style={{ marginTop: '1.1rem' }}>
                      <h3>Sign-off</h3>
                    </div>
                    <div className="wp-signoff">
                      <label>
                        Preparer
                        <input
                          value={preparer}
                          onChange={(e) => {
                            setPreparer(e.target.value)
                            persist(checked, notes, e.target.value, reviewer)
                          }}
                          placeholder="Initials"
                        />
                      </label>
                      <label>
                        Reviewer
                        <input
                          value={reviewer}
                          onChange={(e) => {
                            setReviewer(e.target.value)
                            persist(checked, notes, preparer, e.target.value)
                          }}
                          placeholder="Initials"
                        />
                      </label>
                    </div>
                    <label className="wp-notes">
                      Notes
                      <textarea
                        value={notes}
                        rows={4}
                        onChange={(e) => {
                          setNotes(e.target.value)
                          persist(checked, e.target.value, preparer, reviewer)
                        }}
                        placeholder="Exceptions, conclusions, open items…"
                      />
                    </label>
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
