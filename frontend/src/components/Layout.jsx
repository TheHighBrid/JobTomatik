import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard, Search, ListTodo, ClipboardList, HeartPulse,
  User, Settings, LogOut, Menu, X
} from 'lucide-react'
import { useAuthStore, useNotificationStore } from '../store'
import { getUnreadCount } from '../api/client'
import NotificationBell from './NotificationBell'
import MobileNav from './MobileNav'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/search', icon: Search, label: 'Job Search' },
  { to: '/queue', icon: ListTodo, label: 'Queue' },
  { to: '/applications', icon: ClipboardList, label: 'Applications' },
  { to: '/adapter-health', icon: HeartPulse, label: 'Adapter Health' },
  { to: '/profile', icon: User, label: 'Profile' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function Layout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const { setUnreadCount } = useNotificationStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => { setSidebarOpen(false) }, [location.pathname])

  useEffect(() => {
    if (!sidebarOpen) return undefined

    const onKeyDown = (event) => {
      if (event.key === 'Escape') setSidebarOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [sidebarOpen])

  useEffect(() => {
    let active = true

    const fetchUnreadCount = async () => {
      if (document.visibilityState === 'hidden') return
      try {
        const res = await getUnreadCount()
        if (active) setUnreadCount(res.data.count)
      } catch {
        // Notification polling is non-critical and retries on the next visible interval.
      }
    }

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') fetchUnreadCount()
    }

    fetchUnreadCount()
    const interval = window.setInterval(fetchUnreadCount, 30_000)
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      active = false
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [setUnreadCount])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const SidebarContent = () => (
    <>
      <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-tomato-600 rounded-lg flex items-center justify-center text-white font-bold text-sm">
            JT
          </div>
          <span className="font-bold text-gray-900 text-lg">JobTomatik</span>
        </div>
        <button
          type="button"
          onClick={() => setSidebarOpen(false)}
          className="md:hidden p-1 rounded-lg text-gray-400 hover:bg-gray-100"
          aria-label="Close navigation menu"
        >
          <X className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto" aria-label="Primary navigation">
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
            <Icon className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
            {label}
          </NavLink>
        ))}
      </nav>

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
          type="button"
          onClick={handleLogout}
          className="mt-1 w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-600 hover:bg-red-50 hover:text-red-600 transition-colors"
        >
          <LogOut className="w-4 h-4" aria-hidden="true" />
          Sign out
        </button>
      </div>
    </>
  )

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      <aside className="hidden md:flex w-64 bg-white border-r border-gray-100 flex-col shadow-sm flex-shrink-0">
        <SidebarContent />
      </aside>

      {sidebarOpen && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation menu">
          <button
            type="button"
            className="absolute inset-0 bg-black/40 cursor-default"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close navigation menu"
          />
          <aside
            id="mobile-sidebar"
            className="absolute left-0 top-0 bottom-0 w-72 bg-white flex flex-col shadow-xl"
          >
            <SidebarContent />
          </aside>
        </div>
      )}

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <header className="bg-white border-b border-gray-100 px-4 md:px-6 py-3 flex items-center justify-between gap-4 shadow-sm flex-shrink-0">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="md:hidden p-2 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors"
            aria-label="Open navigation menu"
            aria-expanded={sidebarOpen}
            aria-controls="mobile-sidebar"
          >
            <Menu className="w-5 h-5" aria-hidden="true" />
          </button>
          <div className="md:hidden flex items-center gap-2">
            <div className="w-6 h-6 bg-tomato-600 rounded-md flex items-center justify-center text-white font-bold text-xs">
              JT
            </div>
            <span className="font-bold text-gray-900">JobTomatik</span>
          </div>
          <div className="flex-1" />
          <NotificationBell />
        </header>

        <main className="flex-1 overflow-y-auto p-4 md:p-6 pb-20 md:pb-6">
          <Outlet />
        </main>
      </div>

      <MobileNav />
    </div>
  )
}
