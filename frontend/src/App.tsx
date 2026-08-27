import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Layout } from './components/Layout'
import { BankAccountsPage } from './pages/BankAccountsPage'
import { ClosePackPage } from './pages/ClosePackPage'
import { HomePage } from './pages/HomePage'
import { SettingsPage } from './pages/SettingsPage'
import { StatementsPage } from './pages/StatementsPage'
import { TransactionsPage } from './pages/TransactionsPage'
import { WorkingPapersPage } from './pages/WorkingPapersPage'

/** Preserve query string when remapping legacy routes. */
function LegacyRedirect({ to }: { to: string }) {
  const loc = useLocation()
  const [path, preset = ''] = to.split('?')
  const next = new URLSearchParams(preset)
  const incoming = new URLSearchParams(loc.search)
  incoming.forEach((v, k) => {
    if (!next.has(k)) next.set(k, v)
  })
  const qs = next.toString()
  return <Navigate to={qs ? `${path}?${qs}` : path} replace />
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="work" element={<ClosePackPage />} />
        <Route path="binder" element={<WorkingPapersPage />} />
        <Route path="statements" element={<StatementsPage />} />
        {/* Legacy redirects — keep bookmarks + deep links alive */}
        <Route path="close" element={<LegacyRedirect to="/work" />} />
        <Route path="working-papers" element={<LegacyRedirect to="/binder" />} />
        <Route path="reports" element={<LegacyRedirect to="/statements?tab=statement" />} />
        <Route path="sales" element={<LegacyRedirect to="/statements?tab=sales" />} />
        <Route path="expenses" element={<LegacyRedirect to="/statements?tab=expenses" />} />
        <Route path="budget" element={<LegacyRedirect to="/statements?tab=budget" />} />
        <Route path="reconciliation" element={<LegacyRedirect to="/work" />} />
        <Route path="dashboard" element={<Navigate to="/" replace />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="bank-accounts" element={<BankAccountsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
