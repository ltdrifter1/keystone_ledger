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
  counterparty?: string
  reference?: string
  counter_entity_id?: number
  intercompany_match_id?: number
  entity_code?: string
  account_code?: string
  account_name?: string
  bank_account_name?: string
  splits?: Array<{ id: number; account_id: number; amount: string; memo?: string }>
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

export type Report = {
  report_type: string
  title: string
  currency: string
  generated_at: string
  lines: Array<{
    line_code: string
    line_label: string
    section: string
    amount: string
    compare_amount?: string
    variance?: string
    indent_level: number
    is_bold: boolean
    is_total: boolean
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
  categorize: (id: number, body: { account_id: number; create_rule?: boolean; rule_name?: string }) =>
    request<Transaction>(`/transactions/${id}/categorize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  bulkCategorize: (transaction_ids: number[], account_id: number, create_rule = false) =>
    request<{ categorized: number }>('/transactions/bulk-categorize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transaction_ids, account_id, create_rule }),
    }),
  applyRules: () => request<{ categorized: number }>('/transactions/apply-rules', { method: 'POST' }),
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
  reconItems: (id: number) =>
    request<
      Array<{
        id: number
        transaction_id: number
        is_cleared: boolean
        txn_date: string
        description: string
        amount: number
        currency: string
      }>
    >(`/reconciliations/${id}/items`),
  clearReconItems: (id: number, transaction_ids: number[], is_cleared = true) =>
    request<Reconciliation>(`/reconciliations/${id}/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transaction_ids, is_cleared }),
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
