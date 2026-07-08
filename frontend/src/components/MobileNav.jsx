import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Search, ListTodo, ClipboardList, User } from 'lucide-react'

const TABS = [
  { to: '/', icon: LayoutDashboard, label: 'Home' },
  { to: '/search', icon: Search, label: 'Search' },
  { to: '/queue', icon: ListTodo, label: 'Queue' },
  { to: '/applications', icon: ClipboardList, label: 'Apps' },
  { to: '/profile', icon: User, label: 'Profile' },
]

export default function MobileNav() {
  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-100 z-50 md:hidden safe-area-pb">
      <div className="flex items-stretch h-16">
        {TABS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex-1 flex flex-col items-center justify-center gap-0.5 transition-colors ${
                isActive ? 'text-tomato-600' : 'text-gray-400'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <div className={`p-1 rounded-lg transition-colors ${isActive ? 'bg-tomato-50' : ''}`}>
                  <Icon className="w-5 h-5" />
                </div>
                <span className="text-[10px] font-medium">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
