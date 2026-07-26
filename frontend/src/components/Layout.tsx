import { NavLink, Outlet } from 'react-router-dom'
import {
  LayoutDashboard,
  ArrowLeftRight,
  Landmark,
  FileBarChart2,
  Settings,
  Sparkles,
  ClipboardList,
} from 'lucide-react'
import { PeriodChip } from './PeriodChip'
import { usePeriod } from '../period/PeriodContext'

const links = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/close', label: 'Close', icon: Sparkles },
  { to: '/working-papers', label: 'Working Papers', icon: ClipboardList },
  { to: '/transactions', label: 'Transactions', icon: ArrowLeftRight },
  { to: '/reports', label: 'Reports', icon: FileBarChart2 },
  { to: '/bank-accounts', label: 'Bank Accounts', icon: Landmark },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Layout() {
  const { year, month } = usePeriod()
  const periodLinks = links.map((link) => {
    if (link.to === '/close' || link.to === '/working-papers' || link.to === '/reports') {
      const sep = link.to.includes('?') ? '&' : '?'
      return { ...link, to: `${link.to}${sep}year=${year}&month=${month}` }
    }
    return link
  })

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            Keystone <span>Ledger</span>
          </div>
          <div className="brand-sub">Controller reporting · bank to statements</div>
        </div>
        <PeriodChip />
        <nav className="nav">
          {periodLinks.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={label}
              to={to}
              end={to === '/'}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="nav-meta">
          One engagement period for Close, Reports, and the WP binder.
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
