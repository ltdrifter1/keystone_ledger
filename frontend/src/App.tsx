import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { BankAccountsPage } from './pages/BankAccountsPage'
import { ClosePackPage } from './pages/ClosePackPage'
import { HomePage } from './pages/HomePage'
import { SettingsPage } from './pages/SettingsPage'
import { StatementsPage } from './pages/StatementsPage'
import { TransactionsPage } from './pages/TransactionsPage'
import { WorkingPapersPage } from './pages/WorkingPapersPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="work" element={<ClosePackPage />} />
        <Route path="binder" element={<WorkingPapersPage />} />
        <Route path="statements" element={<StatementsPage />} />
        {/* Legacy redirects — keep bookmarks alive */}
        <Route path="close" element={<Navigate to="/work" replace />} />
        <Route path="working-papers" element={<Navigate to="/binder" replace />} />
        <Route path="reports" element={<Navigate to="/statements?tab=statement" replace />} />
        <Route path="sales" element={<Navigate to="/statements?tab=sales" replace />} />
        <Route path="expenses" element={<Navigate to="/statements?tab=expenses" replace />} />
        <Route path="budget" element={<Navigate to="/statements?tab=budget" replace />} />
        <Route path="reconciliation" element={<Navigate to="/work" replace />} />
        <Route path="dashboard" element={<Navigate to="/" replace />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="bank-accounts" element={<BankAccountsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
