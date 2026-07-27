import { useState, useRef, useEffect } from 'react'
import { Bell } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getNotifications, markAllRead, markRead } from '../api/client'
import { useNotificationStore } from '../store'
import { formatDistanceToNow } from 'date-fns'

const TYPE_COLORS = {
  new_match: 'border-blue-400/25 bg-blue-500/15 text-blue-200',
  status_change: 'border-amber-400/25 bg-amber-400/15 text-amber-200',
  interview_request: 'border-purple-400/25 bg-purple-500/15 text-purple-200',
  offer_received: 'border-emerald-400/25 bg-emerald-400/15 text-emerald-200',
  rejection: 'border-red-400/25 bg-red-500/15 text-red-200',
  followup_sent: 'border-cyan-400/25 bg-cyan-500/15 text-cyan-200',
  application_submitted: 'border-tomato-400/25 bg-tomato-600/15 text-tomato-300',
  system: 'border-gray-300/25 bg-gray-100 text-gray-600',
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const { unreadCount, setUnreadCount } = useNotificationStore()
  const qc = useQueryClient()

  const { data } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => getNotifications({ per_page: 20 }),
    refetchInterval: 30_000,
    enabled: open,
    select: (response) => response.data,
  })

  const markAllMut = useMutation({
    mutationFn: markAllRead,
    onSuccess: () => {
      setUnreadCount(0)
      qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })

  useEffect(() => {
    const handler = (event) => {
      if (ref.current && !ref.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="brand-icon-well relative h-10 w-10 text-gray-500 hover:text-white hover:border-tomato-400/40 transition-colors"
        aria-label={unreadCount > 0 ? `${unreadCount} unread notifications` : 'Notifications'}
        aria-expanded={open}
      >
        <Bell className="w-5 h-5" aria-hidden="true" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] bg-tomato-600 text-white text-[10px] font-bold rounded-full flex items-center justify-center px-1 ring-2 ring-navy-800">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-3 w-[calc(100vw-2rem)] max-w-96 card overflow-hidden z-50 animate-slide-in">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
            <div>
              <p className="section-kicker">Activity</p>
              <h3 className="font-semibold text-gray-900">Notifications</h3>
            </div>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={() => markAllMut.mutate()}
                className="text-xs text-tomato-400 hover:text-tomato-300 font-semibold"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto divide-y divide-gray-200">
            {!data?.length ? (
              <div className="px-4 py-10 text-center text-gray-500 text-sm">
                No notifications yet
              </div>
            ) : (
              data.map((notification) => (
                <button
                  type="button"
                  key={notification.id}
                  className={`block w-full px-4 py-3 text-left hover:bg-gray-100 transition-colors ${
                    !notification.read ? 'bg-tomato-600/5' : ''
                  }`}
                  onClick={() => {
                    if (!notification.read) {
                      markRead(notification.id).then(() => {
                        setUnreadCount(Math.max(0, unreadCount - 1))
                        qc.invalidateQueries({ queryKey: ['notifications'] })
                      })
                    }
                  }}
                >
                  <div className="flex items-start gap-3">
                    <span className={`badge mt-0.5 ${TYPE_COLORS[notification.type] || 'border-gray-300/25 bg-gray-100 text-gray-600'}`}>
                      {notification.type.replace(/_/g, ' ')}
                    </span>
                    {!notification.read && <span className="w-2 h-2 rounded-full bg-tomato-400 mt-1.5 flex-shrink-0 ml-auto shadow-[0_0_12px_rgba(77,130,255,.7)]" />}
                  </div>
                  <p className="mt-1.5 text-sm font-semibold text-gray-900">{notification.title}</p>
                  {notification.message && <p className="mt-0.5 text-xs text-gray-500 line-clamp-2">{notification.message}</p>}
                  <p className="mt-1 text-xs text-gray-400">
                    {formatDistanceToNow(new Date(notification.created_at), { addSuffix: true })}
                  </p>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
