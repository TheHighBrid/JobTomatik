import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listApplications, getApplicationStats } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import SupervisedPilotRoster from '../components/SupervisedPilotRoster'
import { ApplicationRowSkeleton } from '../components/Skeleton'
import { ChevronRight, CalendarDays, Download } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

const STATUSES = ['all', 'pending', 'applying', 'applied', 'interviewing', 'offer', 'rejected']

export default function Applications() {
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)

  const { data: stats } = useQuery({
    queryKey: ['appStats'],
    queryFn: () => getApplicationStats(),
    select: (r) => r.data,
  })

  const { data: apps, isLoading } = useQuery({
    queryKey: ['applications', statusFilter, page],
    queryFn: () =>
      listApplications({
        status: statusFilter === 'all' ? undefined : statusFilter,
        page,
        per_page: 20,
      }),
    select: (r) => r.data,
  })

  const handleExport = () => {
    if (!apps?.length) return
    const rows = [
      ['Title', 'Company', 'Location', 'Status', 'Applied At', 'Source', 'Salary Min', 'Salary Max'],
      ...(apps || []).map((a) => [
        a.job?.title || '',
        a.job?.company || '',
        a.job?.location || '',
        a.status,
        a.applied_at ? new Date(a.applied_at).toLocaleDateString() : '',
        a.job?.source || '',
        a.job?.salary_min || '',
        a.job?.salary_max || '',
      ]),
    ]
    const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `jobtomatik-applications-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-5 animate-fade-in pb-24 md:pb-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold text-gray-900">Applications</h1>
          <p className="text-gray-500 mt-1 text-sm">
            {stats?.total ?? 0} total · {stats?.applied ?? 0} applied · {stats?.interviewing ?? 0} interviewing
          </p>
        </div>
        <button
          onClick={handleExport}
          disabled={!apps?.length}
          className="btn-secondary flex items-center gap-1.5 text-sm"
        >
          <Download className="w-4 h-4" />
          Export CSV
        </button>
      </div>

      <SupervisedPilotRoster />

      {/* Status filter pills */}
      <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-4 px-4 md:mx-0 md:px-0">
        {STATUSES.map((s) => {
          const count = s === 'all' ? stats?.total : stats?.[s]
          return (
            <button
              key={s}
              onClick={() => { setStatusFilter(s); setPage(1) }}
              className={`px-3 py-1.5 rounded-lg text-xs md:text-sm font-medium capitalize whitespace-nowrap transition-all flex-shrink-0 ${
                statusFilter === s
                  ? 'bg-tomato-600 text-white'
                  : 'bg-white text-gray-600 border border-gray-200 hover:border-tomato-300'
              }`}
            >
              {s === 'all' ? 'All' : s}
              {count != null && count > 0 && (
                <span className={`ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                  statusFilter === s ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'
                }`}>
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {isLoading ? (
        <div className="card divide-y divide-gray-50">
          {Array(5).fill(0).map((_, i) => <ApplicationRowSkeleton key={i} />)}
        </div>
      ) : !apps?.length ? (
        <div className="card p-12 text-center">
          <div className="text-4xl mb-3">📋</div>
          <p className="font-medium text-gray-700">
            {statusFilter === 'all' ? 'No applications yet.' : `No ${statusFilter} applications.`}
          </p>
          <p className="text-sm text-gray-500 mt-1">
            {statusFilter === 'all' && (
              <>Approve jobs from the <Link to="/queue" className="text-tomato-600 hover:underline">queue</Link> to start.</>
            )}
          </p>
        </div>
      ) : (
        <div className="card divide-y divide-gray-50">
          {apps.map((app) => (
            <Link
              key={app.id}
              to={`/applications/${app.id}`}
              className="flex items-center gap-3 p-4 hover:bg-gray-50 transition-colors"
            >
              <div className="w-10 h-10 rounded-lg bg-tomato-50 flex items-center justify-center text-tomato-700 font-bold text-sm flex-shrink-0">
                {(app.job?.company || '?')[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-gray-900 truncate">
                  {app.job?.title || 'Unknown Position'}
                </div>
                <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
                  <span>{app.job?.company}</span>
                  {app.job?.location && <span className="text-gray-400">· {app.job.location}</span>}
                </div>
                {app.applied_at && (
                  <div className="flex items-center gap-1 text-xs text-gray-400 mt-1">
                    <CalendarDays className="w-3 h-3" />
                    Applied {formatDistanceToNow(new Date(app.applied_at), { addSuffix: true })}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <StatusBadge status={app.status} />
                <ChevronRight className="w-4 h-4 text-gray-300 hidden md:block" />
              </div>
            </Link>
          ))}
        </div>
      )}

      {apps?.length === 20 && (
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
