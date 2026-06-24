import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listApplications } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { Loader2, ChevronRight, CalendarDays } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

const STATUSES = ['all', 'pending', 'applied', 'interviewing', 'offer', 'rejected']

export default function Applications() {
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)

  const { data, isLoading } = useQuery({
    queryKey: ['applications', statusFilter, page],
    queryFn: () =>
      listApplications({
        status: statusFilter === 'all' ? undefined : statusFilter,
        page,
        per_page: 20,
      }),
    select: (r) => r.data,
  })

  const apps = data || []

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Applications</h1>
        <p className="text-gray-500 mt-1">Track every application from start to offer.</p>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 overflow-x-auto pb-1">
        {STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1) }}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium capitalize whitespace-nowrap transition-all ${
              statusFilter === s
                ? 'bg-tomato-600 text-white'
                : 'bg-white text-gray-600 border border-gray-200 hover:border-tomato-300'
            }`}
          >
            {s === 'all' ? 'All' : s}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-tomato-500" />
        </div>
      ) : !apps.length ? (
        <div className="card p-12 text-center text-gray-400">
          <p className="text-lg font-medium mb-1">No applications found</p>
          <p className="text-sm">
            {statusFilter === 'all'
              ? 'Approve jobs from the queue to start applying.'
              : `No ${statusFilter} applications yet.`}
          </p>
        </div>
      ) : (
        <div className="card divide-y divide-gray-50">
          {apps.map((app) => (
            <Link
              key={app.id}
              to={`/applications/${app.id}`}
              className="flex items-center gap-4 p-4 hover:bg-gray-50 transition-colors"
            >
              <div className="w-10 h-10 rounded-lg bg-tomato-50 flex items-center justify-center text-tomato-700 font-bold text-sm flex-shrink-0">
                {(app.job?.company || '?')[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900 text-sm truncate">
                    {app.job?.title || 'Unknown Position'}
                  </span>
                </div>
                <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-3">
                  <span>{app.job?.company}</span>
                  {app.job?.location && <span>· {app.job.location}</span>}
                </div>
                {app.applied_at && (
                  <div className="flex items-center gap-1 text-xs text-gray-400 mt-1">
                    <CalendarDays className="w-3 h-3" />
                    Applied {formatDistanceToNow(new Date(app.applied_at), { addSuffix: true })}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <StatusBadge status={app.status} />
                <ChevronRight className="w-4 h-4 text-gray-300" />
              </div>
            </Link>
          ))}
        </div>
      )}

      {apps.length === 20 && (
        <div className="flex justify-center gap-3">
          <button className="btn-secondary" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <button className="btn-secondary" onClick={() => setPage((p) => p + 1)}>
            Next
          </button>
        </div>
      )}
    </div>
  )
}
