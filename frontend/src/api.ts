const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
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
  outstanding_reconciliations: number
  uncategorized_transactions: number
  unmatched_intercompany: number
  fx_exposure: Array<Record<string, number | string>>
  intercompany_balances: Array<Record<string, number | string>>
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
}

export type ReportLine = {
  line_code: string
  line_label: string
  section: string
  amount: string
  compare_amount?: string
  variance?: string
  indent_level: number
  is_bold: boolean
  is_total: boolean
  account_id?: number | null
  drillable?: boolean
  account_ids?: number[]
  account_type_filter?: string | null
  wp_ref?: string | null
}

export type Report = {
  report_type: string
  title: string
  currency: string
  generated_at: string
  filters?: ReportFilters
  lines: ReportLine[]
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

export const api = {
  health: () => request<{ status: string }>('/health'),
  dashboard: (ccy = 'CAD') => request<Dashboard>(`/dashboard?reporting_currency=${ccy}`),
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
  report: (body: Record<string, unknown>) =>
    request<Report>('/reports/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
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
}
