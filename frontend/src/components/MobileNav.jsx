import { NavLink } from 'react-router-dom'
import { ClipboardList, LayoutDashboard, ListTodo, Search, ShieldCheck, Target } from 'lucide-react'

const TABS = [
  { to: '/', icon: LayoutDashboard, label: 'Home' },
  { to: '/search', icon: Search, label: 'Search' },
  { to: '/current-lever', icon: Target, label: 'Lever' },
  { to: '/autonomy', icon: ShieldCheck, label: 'Control' },
  { to: '/queue', icon: ListTodo, label: 'Queue' },
  { to: '/applications', icon: ClipboardList, label: 'Apps' },
]

export default function MobileNav() {
  return (
    <nav className="mobile-tabbar fixed bottom-0 left-0 right-0 border-t z-50 md:hidden safe-area-pb" aria-label="Mobile navigation">
      <div className="flex items-stretch h-17 px-1">
        {TABS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `relative flex-1 flex flex-col items-center justify-center gap-1 transition-colors ${
                isActive ? 'text-white' : 'text-gray-400'
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && <span className="absolute top-0 h-0.5 w-8 rounded-full bg-tomato-500 shadow-[0_0_14px_rgba(47,107,255,.8)]" />}
                <span className={`inline-flex h-8 w-10 items-center justify-center rounded-xl transition-all ${
                  isActive ? 'bg-tomato-600/20 text-tomato-400 ring-1 ring-tomato-400/25' : ''
                }`}>
                  <Icon className="w-5 h-5" aria-hidden="true" />
                </span>
                <span className="text-[10px] font-semibold tracking-wide">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
