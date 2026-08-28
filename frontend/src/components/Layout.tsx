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
import { useSession } from '../session/SessionContext'

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
  const { user, users, setUser } = useSession()

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
          Flow: <strong>Home</strong> queue → <strong>Work</strong> (live feed) →{' '}
          <strong>Binder</strong> sign-off → <strong>Statements</strong>.
        </div>
        {user && (
          <div className="user-chip" title="Named closer for audit and SoD">
            <span className="period-chip-label">Signed in</span>
            <select
              className="select engagement-chip-select"
              value={user.username}
              onChange={(e) => void setUser(e.target.value)}
              aria-label="Current user"
            >
              {users.map((u) => (
                <option key={u.username} value={u.username}>
                  {u.initials} · {u.display_name}
                </option>
              ))}
            </select>
            <span className="hint">{user.role}</span>
          </div>
        )}
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
