import { NavLink, Outlet } from 'react-router-dom'
import {
  LayoutDashboard,
  ArrowLeftRight,
  Landmark,
  Scale,
  FileBarChart2,
  Settings,
  Sparkles,
  ClipboardList,
} from 'lucide-react'

const links = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/close', label: 'Close Pack', icon: Sparkles },
  { to: '/working-papers', label: 'Working Papers', icon: ClipboardList },
  { to: '/transactions', label: 'Transactions', icon: ArrowLeftRight },
  { to: '/reconciliation', label: 'Reconciliation', icon: Scale },
  { to: '/reports', label: 'Reports', icon: FileBarChart2 },
  { to: '/bank-accounts', label: 'Bank Accounts', icon: Landmark },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            Keystone <span>Ledger</span>
          </div>
          <div className="brand-sub">Controller reporting · bank to statements</div>
        </div>
        <nav className="nav">
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="nav-meta">
          Month-end is an exception pass.
          <br />
          Upload → auto-clear → lock.
          <br />
          <span className="kbd">/</span> search · <span className="kbd">R</span> rules ·{' '}
          <span className="kbd">S</span> split
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
