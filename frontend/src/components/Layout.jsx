import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import {
  LayoutDashboard, Search, ListTodo, ClipboardList,
  User, Settings, LogOut
} from 'lucide-react'
import { useAuthStore, useNotificationStore } from '../store'
import { getUnreadCount } from '../api/client'
import NotificationBell from './NotificationBell'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/search', icon: Search, label: 'Job Search' },
  { to: '/queue', icon: ListTodo, label: 'Queue' },
  { to: '/applications', icon: ClipboardList, label: 'Applications' },
  { to: '/profile', icon: User, label: 'Profile' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function Layout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const { setUnreadCount } = useNotificationStore()

  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await getUnreadCount()
        setUnreadCount(res.data.count)
      } catch {}
    }
    fetch()
    const interval = setInterval(fetch, 30_000)
    return () => clearInterval(interval)
  }, [])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 bg-white border-r border-gray-100 flex flex-col shadow-sm">
        {/* Brand */}
        <div className="px-6 py-5 border-b border-gray-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-tomato-600 rounded-lg flex items-center justify-center text-white font-bold text-sm">
              JT
            </div>
            <span className="font-bold text-gray-900 text-lg">JobTomatik</span>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                  isActive
                    ? 'bg-tomato-50 text-tomato-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`
              }
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* User footer */}
        <div className="px-3 py-4 border-t border-gray-100">
          <div className="flex items-center gap-3 px-3 py-2 rounded-lg">
            <div className="w-8 h-8 rounded-full bg-tomato-100 flex items-center justify-center text-tomato-700 font-semibold text-sm">
              {(user?.full_name || user?.email || 'U')[0].toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-gray-900 truncate">
                {user?.full_name || 'Account'}
              </div>
              <div className="text-xs text-gray-500 truncate">{user?.email}</div>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="mt-1 w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-600 hover:bg-red-50 hover:text-red-600 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="bg-white border-b border-gray-100 px-6 py-3 flex items-center justify-end gap-4 shadow-sm">
          <NotificationBell />
        </header>

        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
