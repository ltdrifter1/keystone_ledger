import { NavLink, Outlet } from 'react-router-dom'
import {
  LayoutDashboard,
  Sparkles,
  ClipboardList,
  FileBarChart2,
  Settings,
  Landmark,
} from 'lucide-react'
import { EngagementChip } from './PeriodChip'
import { useEngagement } from '../period/PeriodContext'

const primary = [
  { to: '/', label: 'Home', icon: LayoutDashboard },
  { to: '/work', label: 'Work', icon: Sparkles },
  { to: '/binder', label: 'Binder', icon: ClipboardList },
  { to: '/statements', label: 'Statements', icon: FileBarChart2 },
]

const secondary = [
  { to: '/bank-accounts', label: 'Banks', icon: Landmark },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Layout() {
  const { year, month, entityCode, label } = useEngagement()

  const withPeriod = (to: string) => {
    const sep = to.includes('?') ? '&' : '?'
    return `${to}${sep}year=${year}&month=${month}`
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            Keystone <span>Ledger</span>
          </div>
          <div className="brand-sub">
            {entityCode ?? '—'} · {label} · engagement close
          </div>
        </div>
        <EngagementChip />
        <nav className="nav">
          {primary.map(({ to, label: name, icon: Icon }) => (
            <NavLink
              key={name}
              to={withPeriod(to)}
              end={to === '/'}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              <Icon size={16} />
              {name}
            </NavLink>
          ))}
        </nav>
        <div className="nav-divider" />
        <nav className="nav nav-secondary">
          {secondary.map(({ to, label: name, icon: Icon }) => (
            <NavLink key={name} to={to} className={({ isActive }) => (isActive ? 'active' : '')}>
              <Icon size={16} />
              {name}
            </NavLink>
          ))}
        </nav>
        <div className="nav-meta">
          Flow: <strong>Home</strong> queue → <strong>Work</strong> (bank desk) →{' '}
          <strong>Binder</strong> sign-off → <strong>Statements</strong>.
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
