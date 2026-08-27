import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ReportsPage } from './ReportsPage'
import { BudgetPage, ExpensesPage, SalesPage } from './OpsViewsPage'
import { useEngagement } from '../period/PeriodContext'

const TABS = [
  { id: 'statement', label: 'Statement' },
  { id: 'sales', label: 'Sales' },
  { id: 'expenses', label: 'Expenses' },
  { id: 'budget', label: 'Budget' },
] as const

type TabId = (typeof TABS)[number]['id']

export function StatementsPage() {
  const [params, setParams] = useSearchParams()
  const { year, month, setPeriod } = useEngagement()
  const tabParam = params.get('tab') || 'statement'
  const tab: TabId = TABS.some((t) => t.id === tabParam) ? (tabParam as TabId) : 'statement'

  useEffect(() => {
    const y = params.get('year')
    const m = params.get('month')
    if (y && m) setPeriod(Number(y), Number(m))
  }, [params, setPeriod])

  const setTab = (next: TabId) => {
    const p = new URLSearchParams(params)
    p.set('tab', next)
    p.set('year', String(year))
    p.set('month', String(month))
    setParams(p, { replace: true })
  }

  const body = useMemo(() => {
    if (tab === 'sales') return <SalesPage embedded />
    if (tab === 'expenses') return <ExpensesPage embedded />
    if (tab === 'budget') return <BudgetPage embedded />
    return <ReportsPage />
  }, [tab])

  return (
    <div className="statements-hub">
      <div className="statements-tabs" role="tablist" aria-label="Statements">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`statements-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="statements-body">{body}</div>
    </div>
  )
}
