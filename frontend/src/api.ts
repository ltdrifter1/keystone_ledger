const BASE = '/api'
const ACTOR_KEY = 'keystone.user'

export function setActorUsername(username: string) {
  try {
    localStorage.setItem(ACTOR_KEY, username)
  } catch {
    /* ignore */
  }
}

export function getActorUsername(): string | null {
  try {
    return localStorage.getItem(ACTOR_KEY)
  } catch {
    return null
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const actor = getActorUsername()
  if (actor) headers.set('X-Keystone-Actor', actor)
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    const text = await res.text()
    let detail = text
    try {
      detail = JSON.parse(text).detail ?? text
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json()
}

export type Entity = { id: number; code: string; name: string; country: string; functional_currency: string }
export type Account = { id: number; code: string; name: string; account_type: string; statement: string }
export type BankAccount = {
  id: number
  entity_id: number
  name: string
  account_number: string
  currency: string
  institution?: string
  opening_balance: string
  budget_balance?: string | null
}
export type Scenario = { id: number; code: string; name: string; scenario_type: string }
export type Department = { id: number; code: string; name: string; entity_id?: number }
export type Rule = {
  id: number
  name: string
  priority: number
  is_active: boolean
  match_description_contains?: string
  assign_account_id: number
  hit_count: number
}

export type SplitLine = {
  id?: number
  account_id: number
  amount: string | number
  department_id?: number | null
  memo?: string
}

export type Transaction = {
  id: number
  txn_date: string
  description: string
  amount: string
  currency: string
  entity_id: number
  bank_account_id?: number
  account_id?: number
  department_id?: number
  scenario_id: number
  status: string
  is_split: boolean
  is_duplicate: boolean
  is_reconciled: boolean
  is_period_locked?: boolean
  is_editable?: boolean
  counterparty?: string
  reference?: string
  counter_entity_id?: number
  intercompany_match_id?: number
  entity_code?: string
  account_code?: string
  account_name?: string
  bank_account_name?: string
  splits?: SplitLine[]
}

export type DashboardNextAction = {
  key: string
  kind: string
  priority: number
  title: string
  detail: string
  href: string
  count?: number | null
  amount?: number | null
  status?: string | null
}

export type DashboardCloseSummary = {
  period_year: number
  period_month: number
  period_label: string
  banks_total: number
  banks_locked: number
  banks_ready_to_lock: number
  banks_in_progress: number
  can_lock_month: boolean
  all_locked: boolean
  blocking_total: number
}

export type ReconHealthRow = {
  bank_account_id: number
  name: string
  entity_code: string
  currency: string
  balance: string
  budget_balance?: string | null
  variance?: string | null
  variance_pct?: string | null
  on_target?: boolean | null
  target_status: string
  last_reconciled_date?: string | null
  last_reconciled_period?: string | null
  days_since_reconciled?: number | null
  recon_freshness: string
  current_period_status: string
  href: string
}

export type Dashboard = {
  kpis: Array<{
    key: string
    label: string
    value: string
    currency?: string
    format: string
    status?: string
  }>
  cash_by_account: Array<{
    bank_account_id: number
    name: string
    entity_code: string
    currency: string
    balance: string
    balance_reporting: string
  }>
  recon_health?: ReconHealthRow[]
  outstanding_reconciliations: number
  uncategorized_transactions: number
  unmatched_intercompany: number
  fx_exposure: Array<Record<string, number | string>>
  intercompany_balances: Array<Record<string, number | string>>
  close_summary?: DashboardCloseSummary | null
  next_actions?: DashboardNextAction[]
  binder_summary?: {
    period_year: number
    period_month: number
    period_label: string
    total: number
    prepared: number
    reviewed: number
    open: number
    untied: number
    href: string
  } | null
}

export type ReportFilters = {
  report_type: string
  period?: string
  year?: number | null
  month?: number | null
  quarter?: number | null
  scenario_id: number
  compare_scenario_id?: number | null
  entity_ids?: number[] | null
  department_ids?: number[] | null
  reporting_currency?: string
  consolidate?: boolean
  as_of_date?: string | null
  date_from?: string | null
  date_to?: string | null
  compare_prior_period?: boolean
  compare_prior_year?: boolean
  compare_budget?: boolean
  materiality_amount?: number | null
  materiality_pct?: number | null
}

export type ReportLine = {
  line_code: string
  line_label: string
  section: string
  amount: string
  compare_amount?: string
  variance?: string
  prior_period_amount?: string | null
  prior_period_variance?: string | null
  prior_period_variance_pct?: string | null
  prior_year_amount?: string | null
  prior_year_variance?: string | null
  prior_year_variance_pct?: string | null
  budget_amount?: string | null
  budget_variance?: string | null
  budget_variance_pct?: string | null
  flux_flag?: string | null
  flux_note?: string | null
  indent_level: number
  is_bold: boolean
  is_total: boolean
  account_id?: number | null
  drillable?: boolean
  account_ids?: number[]
  account_type_filter?: string | null
  wp_ref?: string | null
}

export type FluxItem = {
  report_type: string
  line_code: string
  line_label: string
  wp_ref?: string | null
  amount: string
  prior_amount?: string | null
  variance?: string | null
  variance_pct?: string | null
  flag: string
  note: string
  drillable: boolean
}

export type Report = {
  report_type: string
  title: string
  currency: string
  generated_at: string
  filters?: ReportFilters
  lines: ReportLine[]
  period_label?: string | null
  prior_period_label?: string | null
  prior_year_label?: string | null
  budget_label?: string | null
  columns?: string[]
  flux?: FluxItem[]
}

export type AnalyticsKpi = {
  key: string
  label: string
  amount: number
  prior_amount?: number | null
  variance?: number | null
  variance_pct?: number | null
  tone?: string | null
}

export type AnalyticsPack = {
  period_label: string
  currency: string
  materiality_amount: string
  materiality_pct: string
  kpis: AnalyticsKpi[]
  flux: FluxItem[]
  statements: Report[]
  generated_at: string
}

export type WorkingPaperTemplate = {
  key: string
  wp_ref: string
  title: string
  statement: string
  section: string
  purpose: string
  objective: string
  tie_out: string
  procedures: string[]
  evidence: string[]
  line_codes: string[]
  account_codes: string[]
  sort_order: number
}

export type WorkingPaperSnippet = {
  key: string
  wp_ref: string
  title: string
  purpose: string
  objective: string
  tie_out: string
  procedures: string[]
  evidence: string[]
}

export type DrillOut = {
  line_code: string
  line_label: string
  wp_ref?: string | null
  report_type: string
  currency: string
  period_label: string
  statement_amount: string
  detail_total: string
  difference: string
  is_tied: boolean
  row_count: number
  generated_at: string
  template?: WorkingPaperSnippet | null
  lines: Array<{
    transaction_id: number
    txn_date: string
    description: string
    entity_id: number
    entity_code?: string
    bank_account_name?: string
    account_id: number
    account_code: string
    account_name: string
    native_amount: string
    currency: string
    reporting_amount: string
    signed_amount: string
    is_split: boolean
    split_memo?: string
    status: string
    is_reconciled: boolean
  }>
}

export type Reconciliation = {
  id: number
  bank_account_id: number
  period_year: number
  period_month: number
  statement_ending_balance: string
  calculated_balance?: string
  difference?: string
  status: string
  uncleared_count: number
  cleared_count: number
  notes?: string
}

export type CloseException = {
  kind: string
  message: string
  transaction_id: number
  txn_date: string
  description: string
  amount: number
  currency: string
  status: string
  is_split: boolean
  is_duplicate: boolean
  is_cleared: boolean
  in_period: boolean
  account_id?: number | null
  account_code?: string | null
  account_name?: string | null
  blocking: boolean
}

export type ClosePackStatus = {
  reconciliation_id?: number | null
  bank_account_id: number
  bank_account_name?: string | null
  entity_id?: number | null
  entity_code?: string | null
  currency?: string | null
  period_year: number
  period_month: number
  period_label: string
  status: string
  beginning_balance: number
  statement_ending_balance?: number | null
  calculated_balance?: number | null
  cleared_total?: number | null
  difference?: number | null
  cleared_count: number
  uncleared_count: number
  exception_count: number
  blocking_count: number
  uncategorized_count?: number
  duplicate_count?: number
  can_lock: boolean
  is_locked: boolean
  exceptions: CloseException[]
  locked_at?: string | null
  locked_by?: string | null
  created_reconciliation?: boolean | null
  auto_cleared?: number | null
  rules_applied?: number | null
  feed_status?: string | null
  feed_pending?: number
  feed_last_synced_at?: string | null
  feed_balance?: number | null
  feed_stale?: boolean | null
  feed_imported?: number | null
  feed_auto_categorized?: number | null
}

export type CloseNextAction = {
  key: string
  kind: string
  priority: number
  title: string
  detail: string
  bank_account_id: number
  bank_account_name?: string | null
  reconciliation_id?: number | null
  mode: string
  filter?: string | null
  count?: number | null
  amount?: number | null
}

export type MonthCloseOverview = {
  period_year: number
  period_month: number
  period_label: string
  banks_total: number
  banks_locked: number
  banks_ready_to_lock: number
  banks_in_progress?: number
  can_lock_month: boolean
  all_locked: boolean
  packs: ClosePackStatus[]
  next_actions: CloseNextAction[]
  newly_locked: number[]
  errors: Array<Record<string, unknown>>
}

export type ReconWorkspace = {
  id: number
  bank_account_id: number
  period_year: number
  period_month: number
  status: string
  beginning_balance: number
  statement_ending_balance: number
  cleared_total: number
  uncleared_total: number
  calculated_balance: number
  difference: number
  cleared_count: number
  uncleared_count: number
  uncategorized_cleared_count: number
  can_lock: boolean
  locked_at?: string | null
  locked_by?: string | null
  notes?: string | null
  items: Array<{
    id: number
    transaction_id: number
    is_cleared: boolean
    txn_date: string
    description: string
    amount: number
    currency: string
    status: string
    is_split: boolean
    account_id?: number | null
    account_code?: string | null
    account_name?: string | null
    in_period: boolean
  }>
}

export type OpsKpi = {
  key: string
  label: string
  amount: number
  compare_amount?: number | null
  variance?: number | null
  variance_pct?: number | null
  tone?: string
}

export type OpsLine = {
  line_code: string
  line_label: string
  section: string
  amount: number
  compare_amount?: number | null
  variance?: number | null
  variance_pct?: number | null
  indent_level: number
  is_bold: boolean
  is_total: boolean
  drillable: boolean
  account_id?: number | null
  account_ids?: number[]
  account_type_filter?: string | null
  wp_ref?: string | null
  href?: string | null
}

export type SalesView = {
  title: string
  period_label: string
  period_year: number
  period_month: number
  currency: string
  entity_id?: number | null
  entity_code?: string | null
  kpis: OpsKpi[]
  lines: OpsLine[]
  top_channels: OpsLine[]
  report_filters: Record<string, unknown>
}

export type ExpensesView = {
  title: string
  period_label: string
  period_year: number
  period_month: number
  currency: string
  entity_id?: number | null
  entity_code?: string | null
  kpis: OpsKpi[]
  lines: OpsLine[]
  report_filters: Record<string, unknown>
}

export type CashBudgetRow = {
  bank_account_id: number
  bank_account_name: string
  entity_code?: string | null
  currency: string
  book_balance: number
  budget_balance?: number | null
  variance?: number | null
  variance_pct?: number | null
  status: string
  href: string
}

export type BudgetView = {
  title: string
  period_label: string
  period_year: number
  period_month: number
  currency: string
  entity_id?: number | null
  entity_code?: string | null
  pnl_kpis: OpsKpi[]
  pnl_lines: OpsLine[]
  cash_rows: CashBudgetRow[]
  budget_facts_ready: boolean
  report_filters: Record<string, unknown>
}

export type BankFeedPending = {
  txn_date: string
  description: string
  amount: string
  currency: string
  external_id?: string | null
  reference?: string | null
  counterparty?: string | null
}

export type BankFeed = {
  id: number
  bank_account_id: number
  bank_account_name: string
  entity_id: number
  entity_code?: string | null
  account_number: string
  currency: string
  institution?: string | null
  provider: string
  status: string
  last_synced_at?: string | null
  last_balance?: string | null
  last_balance_as_of?: string | null
  error_message?: string | null
  connected_at?: string | null
  pending_count: number
  is_stale: boolean
  href: string
  pending: BankFeedPending[]
}

export type FeedSync = {
  bank_account_id: number
  status: string
  imported: number
  duplicates_flagged: number
  auto_categorized: number
  skipped: number
  pending_remaining: number
  last_balance: string
  last_balance_as_of: string
  last_synced_at: string
  statement_ending_balance?: string | null
  errors: string[]
  feed: BankFeed
}

export type EngagementHome = {
  period_year: number
  period_month: number
  period_label: string
  entity_id?: number | null
  entity_code?: string | null
  entity_name?: string | null
  journal_led?: boolean
  month_lock?: {
    entity_id: number
    period_year: number
    period_month: number
    is_locked: boolean
    locked_at?: string | null
    locked_by?: string | null
    notes?: string | null
    journal_led?: boolean
  } | null
  progress: {
    banks_total: number
    banks_locked: number
    blocking_total: number
    uncategorized: number
    binder_total: number
    binder_reviewed: number
    binder_untied: number
    cash_ready: boolean
    feeds_connected?: number
    feeds_pending?: number
    unmatched_ic?: number
    journals?: number
    month_locked?: boolean
    journal_led?: boolean
  }
  queue: Array<{
    key: string
    step: number
    phase: string
    priority: number
    title: string
    detail: string
    href: string
    count?: number | null
    status: string
  }>
  work_href: string
  binder_href: string
  statements_href: string
}

export const api = {
  health: () => request<{ status: string }>('/health'),
  dashboard: (ccy = 'CAD') => request<Dashboard>(`/dashboard?reporting_currency=${ccy}`),
  salesView: (params: { year: number; month: number; entity_id?: number; period?: string }) => {
    const qs = new URLSearchParams({ year: String(params.year), month: String(params.month) })
    if (params.entity_id) qs.set('entity_id', String(params.entity_id))
    if (params.period) qs.set('period', params.period)
    return request<SalesView>(`/views/sales?${qs}`)
  },
  expensesView: (params: { year: number; month: number; entity_id?: number; period?: string }) => {
    const qs = new URLSearchParams({ year: String(params.year), month: String(params.month) })
    if (params.entity_id) qs.set('entity_id', String(params.entity_id))
    if (params.period) qs.set('period', params.period)
    return request<ExpensesView>(`/views/expenses?${qs}`)
  },
  budgetView: (params: { year: number; month: number; entity_id?: number; period?: string }) => {
    const qs = new URLSearchParams({ year: String(params.year), month: String(params.month) })
    if (params.entity_id) qs.set('entity_id', String(params.entity_id))
    if (params.period) qs.set('period', params.period)
    return request<BudgetView>(`/views/budget?${qs}`)
  },
  engagementHome: (params: { year: number; month: number; entity_id?: number }) => {
    const qs = new URLSearchParams({ year: String(params.year), month: String(params.month) })
    if (params.entity_id) qs.set('entity_id', String(params.entity_id))
    return request<EngagementHome>(`/engagement/home?${qs}`)
  },
  entities: () => request<Entity[]>('/entities'),
  accounts: () => request<Account[]>('/accounts'),
  bankAccounts: () => request<BankAccount[]>('/bank-accounts'),
  departments: () => request<Department[]>('/departments'),
  scenarios: () => request<Scenario[]>('/scenarios'),
  rules: () => request<Rule[]>('/rules'),
  auditLog: () => request<Array<Record<string, unknown>>>('/audit-log?limit=50'),
  transactions: (params: Record<string, string | number | boolean | undefined> = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '' && v !== false) qs.set(k, String(v))
    })
    return request<Transaction[]>(`/transactions?${qs}`)
  },
  updateTransaction: (id: number, body: Record<string, unknown>) =>
    request<Transaction>(`/transactions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  categorize: (
    id: number,
    body: {
      account_id: number
      department_id?: number | null
      counter_entity_id?: number | null
      create_rule?: boolean
      rule_name?: string
    },
  ) =>
    request<Transaction>(`/transactions/${id}/categorize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  bulkCategorize: (transaction_ids: number[], account_id: number, create_rule = false) =>
    request<{ categorized: number; skipped_locked?: number }>('/transactions/bulk-categorize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transaction_ids, account_id, create_rule }),
    }),
  splitTransaction: (id: number, splits: Array<{ account_id: number; amount: number; memo?: string }>) =>
    request<Transaction>(`/transactions/${id}/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ splits }),
    }),
  applyRules: () =>
    request<{ categorized: number; skipped_locked?: number }>('/transactions/apply-rules', { method: 'POST' }),
  autoMatchIc: () => request<{ matched: number }>('/transactions/intercompany/auto-match', { method: 'POST' }),
  importBank: async (bankAccountId: number, file: File) => {
    const fd = new FormData()
    fd.append('bank_account_id', String(bankAccountId))
    fd.append('file', file)
    return request<{
      batch_id: string
      imported: number
      duplicates_flagged: number
      auto_categorized: number
      skipped: number
      errors: string[]
    }>('/imports/bank-statement', { method: 'POST', body: fd })
  },
  importSynoptic: async (bankAccountId: number, file: File) => {
    const fd = new FormData()
    fd.append('bank_account_id', String(bankAccountId))
    fd.append('file', file)
    return request<{
      batch_id: string
      imported: number
      duplicates_flagged: number
      auto_categorized: number
      skipped: number
      errors: string[]
    }>('/imports/synoptic', { method: 'POST', body: fd })
  },
  importAdjPack: async (file: File, entityId?: number) => {
    const fd = new FormData()
    fd.append('file', file)
    if (entityId) fd.append('entity_id', String(entityId))
    return request<{
      batch_id: string
      imported: number
      duplicates_flagged: number
      auto_categorized: number
      skipped: number
      errors: string[]
    }>('/imports/adj-pack', { method: 'POST', body: fd })
  },
  report: (body: Record<string, unknown>) =>
    request<Report>('/reports/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  analytics: (body: Record<string, unknown>) =>
    request<AnalyticsPack>('/reports/analytics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  exportStatements: async (body: Record<string, unknown>) => {
    const res = await fetch(`${BASE}/reports/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || 'Export failed')
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `keystone-statements.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  },
  bankFeeds: (entityId?: number) => {
    const qs = entityId ? `?entity_id=${entityId}` : ''
    return request<BankFeed[]>(`/bank-feeds${qs}`)
  },
  connectFeed: (bankAccountId: number) =>
    request<BankFeed>(`/bank-feeds/${bankAccountId}/connect`, { method: 'POST' }),
  disconnectFeed: (bankAccountId: number) =>
    request<BankFeed>(`/bank-feeds/${bankAccountId}/disconnect`, { method: 'POST' }),
  syncFeed: (bankAccountId: number, year?: number, month?: number) => {
    const qs = new URLSearchParams()
    if (year) qs.set('year', String(year))
    if (month) qs.set('month', String(month))
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<FeedSync>(`/bank-feeds/${bankAccountId}/sync${suffix}`, { method: 'POST' })
  },
  drillReport: (body: {
    line_code: string
    account_id?: number | null
    account_ids?: number[] | null
    account_type_filter?: string | null
    filters: ReportFilters
  }) =>
    request<DrillOut>('/reports/drill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  reconciliations: () => request<Reconciliation[]>('/reconciliations'),
  createReconciliation: (body: {
    bank_account_id: number
    period_year: number
    period_month: number
    statement_ending_balance: number
  }) =>
    request<Reconciliation>('/reconciliations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  reconWorkspace: (id: number) => request<ReconWorkspace>(`/reconciliations/${id}/workspace`),
  syncRecon: (id: number) => request<ReconWorkspace & { added?: number }>(`/reconciliations/${id}/sync`, { method: 'POST' }),
  clearReconItems: (id: number, transaction_ids: number[], is_cleared = true) =>
    request<Reconciliation>(`/reconciliations/${id}/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transaction_ids, is_cleared }),
    }),
  clearAllRecon: (id: number, onlyCategorized = true) =>
    request<ReconWorkspace>(`/reconciliations/${id}/clear-all?only_categorized=${onlyCategorized}`, {
      method: 'POST',
    }),
  completeRecon: (id: number) =>
    request<Reconciliation>(`/reconciliations/${id}/complete?lock=true`, { method: 'POST' }),
  createRule: (body: Record<string, unknown>) =>
    request<Rule>('/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  closeMonthOverview: (year: number, month: number) =>
    request<MonthCloseOverview>(`/close-pack/month?year=${year}&month=${month}`),
  runClosePack: async (args: {
    bankAccountId: number
    periodYear: number
    periodMonth: number
    statementEndingBalance: number
    file?: File | null
  }) => {
    const fd = new FormData()
    fd.append('bank_account_id', String(args.bankAccountId))
    fd.append('period_year', String(args.periodYear))
    fd.append('period_month', String(args.periodMonth))
    fd.append('statement_ending_balance', String(args.statementEndingBalance))
    if (args.file) fd.append('file', args.file)
    return request<ClosePackStatus>('/close-pack/run', { method: 'POST', body: fd })
  },
  runCloseFromFeed: async (args: { bankAccountId: number; periodYear: number; periodMonth: number }) => {
    const fd = new FormData()
    fd.append('bank_account_id', String(args.bankAccountId))
    fd.append('period_year', String(args.periodYear))
    fd.append('period_month', String(args.periodMonth))
    return request<ClosePackStatus>('/close-pack/run-from-feed', { method: 'POST', body: fd })
  },
  getClosePack: (reconId: number) => request<ClosePackStatus>(`/close-pack/${reconId}`),
  refreshClosePack: (reconId: number) =>
    request<ClosePackStatus>(`/close-pack/${reconId}/refresh`, { method: 'POST' }),
  closeCategorizeException: (
    reconId: number,
    txnId: number,
    body: { account_id: number; create_rule?: boolean; clear_after?: boolean },
  ) =>
    request<ClosePackStatus>(`/close-pack/${reconId}/exceptions/${txnId}/categorize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  closeClearException: (reconId: number, txnId: number, is_cleared = true) =>
    request<ClosePackStatus>(`/close-pack/${reconId}/exceptions/${txnId}/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_cleared }),
    }),
  closeVoidDuplicate: (reconId: number, txnId: number) =>
    request<ClosePackStatus>(`/close-pack/${reconId}/exceptions/${txnId}/void-duplicate`, {
      method: 'POST',
    }),
  lockClosePack: (reconId: number) =>
    request<ClosePackStatus>(`/close-pack/${reconId}/lock`, { method: 'POST' }),
  lockMonth: (year: number, month: number) =>
    request<MonthCloseOverview>(`/close-pack/month/lock?year=${year}&month=${month}`, { method: 'POST' }),
  entityPeriodLock: (entityId: number, year: number, month: number) =>
    request<{
      entity_id: number
      period_year: number
      period_month: number
      is_locked: boolean
      locked_at?: string | null
      locked_by?: string | null
      notes?: string | null
      journal_led?: boolean
    }>(`/period-locks?entity_id=${entityId}&year=${year}&month=${month}`),
  lockEntityMonth: (entityId: number, year: number, month: number, notes?: string) => {
    const qs = new URLSearchParams({
      entity_id: String(entityId),
      year: String(year),
      month: String(month),
    })
    if (notes) qs.set('notes', notes)
    return request<{
      entity_id: number
      period_year: number
      period_month: number
      is_locked: boolean
      locked_at?: string | null
      locked_by?: string | null
      notes?: string | null
      journal_led?: boolean
    }>(`/period-locks/lock?${qs}`, { method: 'POST' })
  },
  workingPapers: () =>
    request<{ templates: WorkingPaperTemplate[]; count: number }>('/working-papers'),
  workingPaper: (key: string) => request<WorkingPaperTemplate>(`/working-papers/${key}`),
  binder: (year: number, month: number, entityId?: number | string) => {
    const qs = new URLSearchParams({ year: String(year), month: String(month) })
    if (entityId) qs.set('entity_id', String(entityId))
    return request<BinderOut>(`/working-papers/binder?${qs}`)
  },
  binderDocument: (key: string, year: number, month: number, entityId?: number | string) => {
    const qs = new URLSearchParams({ year: String(year), month: String(month) })
    if (entityId) qs.set('entity_id', String(entityId))
    return request<BinderDocument>(`/working-papers/binder/${key}?${qs}`)
  },
  updateBinderDocument: (
    key: string,
    year: number,
    month: number,
    body: {
      checked?: number[]
      notes?: string | null
      preparer?: string | null
      reviewer?: string | null
      status?: string | null
    },
    entityId?: number | string,
  ) => {
    const qs = new URLSearchParams({ year: String(year), month: String(month) })
    if (entityId) qs.set('entity_id', String(entityId))
    return request<BinderDocument>(`/working-papers/binder/${key}?${qs}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },
  session: () => request<SessionPayload>('/session'),
  switchSession: (username: string) =>
    request<SessionPayload>('/session/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username }),
    }),
  postJournal: (body: {
    txn_date: string
    entity_id: number
    description: string
    lines: Array<{ account_id: number; debit?: number | string; credit?: number | string; memo?: string }>
    memo?: string
    working_paper_key?: string
    source_transaction_id?: number
    currency?: string
    post_close?: boolean
    reverse_next_month?: boolean
  }) =>
    request<JournalVoucher>('/journals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  journals: (params: { year?: number; month?: number; entity_id?: number; working_paper_key?: string }) => {
    const qs = new URLSearchParams()
    if (params.year) qs.set('year', String(params.year))
    if (params.month) qs.set('month', String(params.month))
    if (params.entity_id) qs.set('entity_id', String(params.entity_id))
    if (params.working_paper_key) qs.set('working_paper_key', params.working_paper_key)
    return request<JournalVoucher[]>(`/journals?${qs}`)
  },
  attachments: (entity_table: string, entity_id: number) =>
    request<EvidenceFile[]>(`/attachments?entity_table=${entity_table}&entity_id=${entity_id}`),
  uploadAttachment: async (entity_table: string, entity_id: number, file: File) => {
    const fd = new FormData()
    fd.append('entity_table', entity_table)
    fd.append('entity_id', String(entity_id))
    fd.append('file', file)
    return request<EvidenceFile>('/attachments', { method: 'POST', body: fd })
  },
  deleteAttachment: (id: number) => request<{ deleted: number }>(`/attachments/${id}`, { method: 'DELETE' }),
}

export type BinderDocumentIndex = {
  key: string
  wp_ref: string
  title: string
  statement: string
  section: string
  purpose: string
  line_code: string
  statement_amount: number
  currency: string
  is_tied?: boolean | null
  difference?: number | null
  status: string
  procedure_count: number
  procedures_done: number
  procedure_pct: number
  preparer?: string | null
  preparer_at?: string | null
  reviewer?: string | null
  reviewer_at?: string | null
  close_status?: string | null
  href: string
  report_href: string
  close_href?: string | null
}

export type BinderOut = {
  period_year: number
  period_month: number
  period_label: string
  period_end: string
  entity_id?: number | null
  documents: BinderDocumentIndex[]
  summary: {
    total: number
    prepared: number
    reviewed: number
    open: number
    untied: number
    cash_close?: {
      banks_total: number
      banks_locked: number
      banks_ready_to_lock: number
      all_locked: boolean
      blocking_total: number
    } | null
  }
}

export type CashBankScheduleRow = {
  bank_account_id: number
  bank_account_name?: string | null
  entity_code?: string | null
  currency: string
  reconciliation_id?: number | null
  status: string
  beginning_balance: number
  book_balance: number
  book_balance_reporting: number
  book_cleared?: number | null
  statement_ending_balance?: number | null
  statement_reporting?: number | null
  difference?: number | null
  uncleared_count: number
  blocking_count: number
  prior_item_count: number
  prior_samples: string[]
  can_lock: boolean
  is_locked: boolean
  is_tied: boolean
  href: string
}

export type CashReconSchedule = {
  period_year: number
  period_month: number
  period_label: string
  period_end: string
  reporting_currency: string
  banks: CashBankScheduleRow[]
  gl_statement_amount: number
  banks_book_reporting_total: number
  banks_statement_reporting_total: number
  gl_vs_books_difference: number
  banks_total: number
  banks_tied: number
  banks_locked: number
  banks_ready_or_locked: number
  all_started: boolean
  all_bank_tied: boolean
  all_locked: boolean
  all_ready_or_locked: boolean
  gl_agrees: boolean
  is_tied: boolean
  can_prepare: boolean
  can_review: boolean
  gate_messages: string[]
  auto_checked: number[]
  close_status: string
}

export type BinderDocument = BinderDocumentIndex & {
  period_year: number
  period_month: number
  period_label: string
  period_end: string
  document_id?: number | null
  objective: string
  tie_out: string
  procedures: string[]
  evidence: string[]
  checked: number[]
  notes?: string | null
  cash_schedule?: CashReconSchedule | null
  schedule?: WpSchedule | null
  attachments?: EvidenceFile[]
  attachment_count?: number
  can_prepare?: boolean
  can_review?: boolean
  gate_messages?: string[]
  drill?: {
    line_code: string
    line_label: string
    wp_ref?: string | null
    statement_amount: number
    detail_total: number
    difference: number
    is_tied: boolean
    row_count: number
    period_label: string
    currency: string
    lines: Array<{
      transaction_id: number
      txn_date: string
      description: string
      entity_code?: string
      account_code: string
      account_name: string
      signed_amount: number
      currency: string
      is_reconciled: boolean
    }>
  } | null
}

export type SessionUser = {
  id: number
  username: string
  display_name: string
  initials: string
  role: string
}

export type SessionPayload = { user: SessionUser; users: SessionUser[] }

export type JournalVoucher = {
  id: number
  voucher?: string | null
  txn_date: string
  description: string
  memo?: string | null
  entity_id: number
  entity_code?: string | null
  currency: string
  lines: Array<{
    account_id: number
    account_code?: string
    account_name?: string
    debit: number
    credit: number
    amount: number
    memo?: string | null
  }>
  created_by?: string | null
}

export type EvidenceFile = {
  id: number
  filename: string
  content_type?: string
  uploaded_by?: string
  uploaded_at?: string | null
  size_bytes?: number | null
}

export type WpSchedule = {
  kind: string
  key?: string
  line_code?: string
  is_tied: boolean
  gl_amount: number
  difference: number
  schedule_total?: number
  gate_messages?: string[]
  can_prepare?: boolean
  can_review?: boolean
  buckets?: Record<string, number>
  parties?: Array<{
    counterparty: string
    current: number
    days_31_60: number
    days_61_90: number
    days_91_plus: number
    total: number
    count: number
  }>
  opening?: number
  additions?: number
  reductions?: number
  closing?: number
  accounts?: Array<{
    account_code: string
    account_name: string
    opening?: number
    additions?: number
    reductions?: number
    closing?: number
    total?: number
    count?: number
  }>
  period_lines?: Array<{
    transaction_id: number
    txn_date: string
    description: string
    account_code: string
    signed_amount: number
    source_type?: string
  }>
  unmatched_count?: number
  matched_count?: number
  ic_mirror?: {
    entity_code?: string | null
    counter_entity_code?: string | null
    ours: { ar: number; ap: number; ic: number }
    theirs: { ar: number; ap: number; ic: number }
    ours_net: number
    theirs_net: number
    difference: number
    is_mirrored: boolean
    currency: string
    period_label: string
  } | null
  unmatched?: Array<{
    transaction_id: number
    txn_date: string
    description: string
    entity_code?: string
    signed_amount: number
  }>
  matched?: Array<{
    transaction_id: number
    txn_date: string
    description: string
    entity_code?: string
    signed_amount: number
  }>
  lines?: Array<{
    transaction_id: number
    txn_date: string
    description: string
    account_code: string
    signed_amount: number
  }>
  row_count?: number
}
