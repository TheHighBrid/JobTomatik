import { useState, useRef, useEffect } from 'react'
import { Bell } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getNotifications, markAllRead, markRead } from '../api/client'
import { useNotificationStore } from '../store'
import { formatDistanceToNow } from 'date-fns'

const TYPE_COLORS = {
  new_match: 'bg-blue-100 text-blue-700',
  status_change: 'bg-yellow-100 text-yellow-700',
  interview_request: 'bg-purple-100 text-purple-700',
  offer_received: 'bg-green-100 text-green-700',
  rejection: 'bg-red-100 text-red-700',
  followup_sent: 'bg-teal-100 text-teal-700',
  application_submitted: 'bg-tomato-100 text-tomato-700',
  system: 'bg-gray-100 text-gray-700',
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
    select: (r) => r.data,
  })

  const markAllMut = useMutation({
    mutationFn: markAllRead,
    onSuccess: () => {
      setUnreadCount(0)
      qc.invalidateQueries(['notifications'])
    },
  })

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative p-2 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] bg-tomato-600 text-white text-[10px] font-bold rounded-full flex items-center justify-center px-1">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-96 bg-white rounded-xl shadow-xl border border-gray-100 z-50 animate-slide-in">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <h3 className="font-semibold text-gray-900">Notifications</h3>
            {unreadCount > 0 && (
              <button
                onClick={() => markAllMut.mutate()}
                className="text-xs text-tomato-600 hover:text-tomato-700 font-medium"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto divide-y divide-gray-50">
            {!data?.length ? (
              <div className="px-4 py-8 text-center text-gray-500 text-sm">
                No notifications yet
              </div>
            ) : (
              data.map((n) => (
                <div
                  key={n.id}
                  className={`px-4 py-3 hover:bg-gray-50 transition-colors cursor-pointer ${!n.read ? 'bg-blue-50/50' : ''}`}
                  onClick={() => {
                    if (!n.read) {
                      markRead(n.id).then(() => {
                        setUnreadCount(Math.max(0, unreadCount - 1))
                        qc.invalidateQueries(['notifications'])
                      })
                    }
                  }}
                >
                  <div className="flex items-start gap-3">
                    <span className={`badge mt-0.5 ${TYPE_COLORS[n.type] || 'bg-gray-100 text-gray-600'}`}>
                      {n.type.replace(/_/g, ' ')}
                    </span>
                    {!n.read && <div className="w-2 h-2 rounded-full bg-tomato-500 mt-1.5 flex-shrink-0 ml-auto" />}
                  </div>
                  <p className="mt-1.5 text-sm font-medium text-gray-900">{n.title}</p>
                  {n.message && <p className="mt-0.5 text-xs text-gray-500 line-clamp-2">{n.message}</p>}
                  <p className="mt-1 text-xs text-gray-400">
                    {formatDistanceToNow(new Date(n.created_at), { addSuffix: true })}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
