import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { BankAccountsPage } from './pages/BankAccountsPage'
import { DashboardPage } from './pages/DashboardPage'
import { ReconciliationPage } from './pages/ReconciliationPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage } from './pages/SettingsPage'
import { TransactionsPage } from './pages/TransactionsPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="reconciliation" element={<ReconciliationPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="bank-accounts" element={<BankAccountsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
