import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard, BrainCircuit, PanelsTopLeft, CalendarClock, Workflow, Fingerprint, MailCheck, Search, ListTodo, ClipboardList, BookOpenCheck,
  HeartPulse, User, Settings, LogOut, Menu, X
} from 'lucide-react'
import { useAuthStore, useNotificationStore } from '../store'
import { getUnreadCount } from '../api/client'
import NotificationBell from './NotificationBell'
import MobileNav from './MobileNav'
import { BrandMark, BrandWordmark } from './BrandLogo'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/command-center', icon: BrainCircuit, label: 'Command Center' },
  { to: '/operations', icon: PanelsTopLeft, label: 'Operations Center' },
  { to: '/scheduler', icon: CalendarClock, label: 'Scheduler Center' },
  { to: '/execution', icon: Workflow, label: 'Execution Center' },
  { to: '/handoff-review', icon: Fingerprint, label: 'Handoff Review' },
  { to: '/followup-review', icon: MailCheck, label: 'Follow-up Review' },
  { to: '/search', icon: Search, label: 'Job Search' },
  { to: '/queue', icon: ListTodo, label: 'Queue' },
  { to: '/applications', icon: ClipboardList, label: 'Applications' },
  { to: '/evidence-materials', icon: BookOpenCheck, label: 'Evidence & Materials' },
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
      <div className="px-5 py-5 border-b border-gray-200 flex items-center justify-between">
        <BrandWordmark />
        <button
          type="button"
          onClick={() => setSidebarOpen(false)}
          className="md:hidden p-2 rounded-xl text-gray-500 hover:text-white hover:bg-gray-100 transition-colors"
          aria-label="Close navigation menu"
        >
          <X className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>

      <div className="mx-4 mt-4 px-4 py-3 rounded-2xl brand-panel">
        <p className="section-kicker">Smart automation</p>
        <p className="mt-1 text-sm font-semibold text-white">Better opportunities, less busywork.</p>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto" aria-label="Primary navigation">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `brand-nav-link flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all duration-150 ${
                isActive ? 'brand-nav-link-active' : ''
              }`
            }
          >
            <span className="brand-icon-well h-8 w-8 flex-shrink-0">
              <Icon className="w-4 h-4" aria-hidden="true" />
            </span>
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="px-3 py-4 border-t border-gray-200">
        <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-gray-100/70 border border-gray-200">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-tomato-400 to-tomato-700 flex items-center justify-center text-white font-bold text-sm shadow-lg shadow-blue-950/30">
            {(user?.full_name || user?.email || 'U')[0].toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-gray-900 truncate">
              {user?.full_name || 'Account'}
            </div>
            <div className="text-xs text-gray-500 truncate">{user?.email}</div>
          </div>
        </div>
        <button
          type="button"
          onClick={handleLogout}
          className="mt-2 w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-gray-500 hover:bg-red-500/10 hover:text-red-300 transition-colors"
        >
          <LogOut className="w-4 h-4" aria-hidden="true" />
          Sign out
        </button>
      </div>
    </>
  )

  return (
    <div className="app-shell flex h-screen overflow-hidden">
      <aside className="app-sidebar hidden md:flex w-72 border-r flex-col flex-shrink-0">
        <SidebarContent />
      </aside>

      {sidebarOpen && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation menu">
          <button
            type="button"
            className="absolute inset-0 bg-black/65 backdrop-blur-sm cursor-default"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close navigation menu"
          />
          <aside
            id="mobile-sidebar"
            className="app-sidebar absolute left-0 top-0 bottom-0 w-[86vw] max-w-80 border-r flex flex-col shadow-2xl"
          >
            <SidebarContent />
          </aside>
        </div>
      )}

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <header className="app-topbar border-b px-4 md:px-6 py-3 flex items-center justify-between gap-4 flex-shrink-0">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="md:hidden p-2 rounded-xl text-gray-500 hover:text-white hover:bg-gray-100 transition-colors"
            aria-label="Open navigation menu"
            aria-expanded={sidebarOpen}
            aria-controls="mobile-sidebar"
          >
            <Menu className="w-5 h-5" aria-hidden="true" />
          </button>
          <div className="md:hidden flex items-center gap-2.5">
            <BrandMark className="h-8 w-8" decorative />
            <span className="font-extrabold tracking-[-0.03em] text-white">
              Job<span className="brand-gradient-text">Tomatik</span>
            </span>
          </div>
          <div className="hidden md:flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">
            <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_14px_rgba(52,211,153,.65)]" />
            Automation workspace
          </div>
          <div className="flex-1" />
          <NotificationBell />
        </header>

        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 pb-24 md:pb-8">
          <div className="mx-auto w-full max-w-[1500px] animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>

      <MobileNav />
    </div>
  )
}
