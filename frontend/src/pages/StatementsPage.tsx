import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ReportsPage } from './ReportsPage'
import { BudgetPage, ExpensesPage, SalesPage } from './OpsViewsPage'
import { AnalyticsPage } from './AnalyticsPage'
import { TrialBalancePage } from './TrialBalancePage'
import { useEngagement } from '../period/PeriodContext'

const PRIMARY = [
  { id: 'pnl', label: 'Profit & Loss' },
  { id: 'bs', label: 'Balance Sheet' },
  { id: 'equity', label: 'Equity' },
  { id: 'tb', label: 'Trial balance' },
] as const

const MORE = [
  { id: 'analytics', label: 'Analytics' },
  { id: 'sales', label: 'Sales' },
  { id: 'expenses', label: 'Expenses' },
  { id: 'budget', label: 'Budget (illustrative)' },
] as const

type TabId = (typeof PRIMARY)[number]['id'] | (typeof MORE)[number]['id']

function normalizeTab(tabParam: string | null, typeParam: string | null): TabId {
  if (tabParam === 'bs' || typeParam === 'balance_sheet') return 'bs'
  if (tabParam === 'equity' || typeParam === 'equity') return 'equity'
  if (tabParam === 'tb' || typeParam === 'trial_balance') return 'tb'
  if (tabParam && MORE.some((t) => t.id === tabParam)) return tabParam as TabId
  return 'pnl'
}

export function StatementsPage() {
  const [params, setParams] = useSearchParams()
  const { year, month, setPeriod } = useEngagement()
  const tab = normalizeTab(params.get('tab'), params.get('type'))

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
    if (next === 'bs') p.set('type', 'balance_sheet')
    else if (next === 'pnl') p.set('type', 'income_statement')
    else if (next === 'equity') p.set('type', 'equity')
    else if (next === 'tb') p.set('type', 'trial_balance')
    else p.delete('type')
    setParams(p, { replace: true })
  }

  const body = useMemo(() => {
    if (tab === 'analytics') return <AnalyticsPage embedded />
    if (tab === 'sales') return <SalesPage embedded />
    if (tab === 'expenses') return <ExpensesPage embedded />
    if (tab === 'budget') return <BudgetPage embedded />
    if (tab === 'tb') return <TrialBalancePage />
    const type = tab === 'bs' ? 'balance_sheet' : tab === 'equity' ? 'equity' : 'income_statement'
    return <ReportsPage forcedType={type} />
  }, [tab])

  return (
    <div className="statements-hub">
      <div className="statements-tabs" role="tablist" aria-label="Statements">
        {PRIMARY.map((t) => (
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
        <span className="statements-tab-divider" aria-hidden="true" />
        {MORE.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`statements-tab statements-tab-more ${tab === t.id ? 'active' : ''}`}
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
