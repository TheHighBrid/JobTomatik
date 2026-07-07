import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getApplicationStats, getJobQueue, listApplications, runAutoPilot, bulkApply } from '../api/client'
import { useAuthStore } from '../store'
import StatusBadge from '../components/StatusBadge'
import { StatCardSkeleton, JobCardSkeleton } from '../components/Skeleton'
import { TrendingUp, Briefcase, Clock, Award, ChevronRight, Search, Zap, ListTodo, Bot, Play, Send, Loader2 } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const CHART_COLORS = {
  pending: '#9ca3af',
  applying: '#3b82f6',
  applied: '#6366f1',
  interviewing: '#a855f7',
  offer: '#22c55e',
  rejected: '#ef4444',
  withdrawn: '#d1d5db',
}

function AutoPilotPanel() {
  const qc = useQueryClient()
  const [dryRun, setDryRun] = useState(true)
  const [msg, setMsg] = useState(null)

  const pilotMut = useMutation({
    mutationFn: () => runAutoPilot({ dry_run: dryRun, min_score: 0.5, daily_limit: 15 }),
    onSuccess: (res) => {
      const d = res.data
      setMsg(`Search started (task ${d.search_task_id?.slice(0,8)}…). Auto-approved ${d.auto_approved} jobs.`)
      qc.invalidateQueries(['jobQueue'])
      qc.invalidateQueries(['appStats'])
    },
    onError: (e) => setMsg('Auto-pilot error: ' + (e.response?.data?.detail || e.message)),
  })

  const bulkMut = useMutation({
    mutationFn: () => bulkApply(dryRun, 20),
    onSuccess: (res) => {
      const d = res.data
      setMsg(`Bulk apply: ${d.applied} applications queued, ${d.skipped} skipped.`)
      qc.invalidateQueries(['appStats'])
    },
    onError: (e) => setMsg('Bulk apply error: ' + (e.response?.data?.detail || e.message)),
  })

  const running = pilotMut.isPending || bulkMut.isPending

  return (
    <div className="card p-5 border-2 border-tomato-100">
      <div className="flex items-center gap-2 mb-3">
        <Bot className="w-5 h-5 text-tomato-600" />
        <h2 className="font-semibold text-gray-900">Auto-Pilot</h2>
        <span className="ml-auto text-xs text-gray-400">Full autonomous mode</span>
      </div>
      <div className="flex flex-wrap gap-3 items-center">
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={!dryRun}
            onChange={(e) => setDryRun(!e.target.checked)}
            className="accent-tomato-600"
          />
          <span className={`font-medium ${!dryRun ? 'text-tomato-700' : 'text-gray-500'}`}>
            {dryRun ? 'Dry Run (safe)' : 'LIVE — will submit real applications'}
          </span>
        </label>
      </div>
      <div className="flex flex-wrap gap-3 mt-3">
        <button
          onClick={() => pilotMut.mutate()}
          disabled={running}
          className="btn-primary flex items-center gap-2 text-sm"
        >
          {pilotMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Search + Auto-Approve
        </button>
        <button
          onClick={() => bulkMut.mutate()}
          disabled={running}
          className={`flex items-center gap-2 text-sm px-4 py-2 rounded-lg font-medium border transition-all ${!dryRun ? 'bg-tomato-600 text-white border-tomato-600 hover:bg-tomato-700' : 'btn-secondary'}`}
        >
          {bulkMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          Bulk Apply to Approved
        </button>
      </div>
      {msg && (
        <div className="mt-3 text-xs text-gray-600 bg-gray-50 px-3 py-2 rounded-lg">{msg}</div>
      )}
      {!dryRun && (
        <p className="mt-2 text-xs text-tomato-600">
          ⚠ Live mode active — applications will be submitted for real. Make sure <code>ALLOW_REAL_APPLICATION_SUBMIT=true</code> is set on the server.
        </p>
      )}
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuthStore()

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['appStats'],
    queryFn: () => getApplicationStats(),
    select: (r) => r.data,
  })

  const { data: queueData, isLoading: queueLoading } = useQuery({
    queryKey: ['jobQueue', { per_page: 5 }],
    queryFn: () => getJobQueue({ per_page: 5 }),
    select: (r) => r.data,
  })

  const { data: recentApps, isLoading: appsLoading } = useQuery({
    queryKey: ['recentApps'],
    queryFn: () => listApplications({ per_page: 5 }),
    select: (r) => r.data,
  })

  const chartData = stats
    ? Object.entries(stats)
        .filter(([k]) => k !== 'total' && stats[k] > 0)
        .map(([key, value]) => ({ name: key, value }))
    : []

  const topStats = [
    { label: 'Total', value: stats?.total ?? 0, icon: Briefcase, color: 'from-blue-500 to-blue-600' },
    { label: 'Applied', value: stats?.applied ?? 0, icon: TrendingUp, color: 'from-indigo-500 to-indigo-600' },
    { label: 'Interviewing', value: stats?.interviewing ?? 0, icon: Clock, color: 'from-purple-500 to-purple-600' },
    { label: 'Offers', value: stats?.offer ?? 0, icon: Award, color: 'from-green-500 to-green-600' },
  ]

  const queueCount = queueData?.total ?? 0

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold text-gray-900">
            Hey{user?.full_name ? ` ${user.full_name.split(' ')[0]}` : ''}! 👋
          </h1>
          <p className="text-gray-500 mt-1 text-sm">Here's your job search overview.</p>
        </div>
        {queueCount > 0 && (
          <Link
            to="/queue"
            className="flex items-center gap-1.5 bg-tomato-600 text-white text-xs font-medium px-3 py-2 rounded-lg hover:bg-tomato-700 transition-colors"
          >
            <Zap className="w-3.5 h-3.5" />
            {queueCount} in queue
          </Link>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {statsLoading
          ? Array(4).fill(0).map((_, i) => <StatCardSkeleton key={i} />)
          : topStats.map(({ label, value, icon: Icon, color }) => (
            <div key={label} className={`card p-4 bg-gradient-to-br ${color} text-white`}>
              <Icon className="w-5 h-5 opacity-80 mb-2" />
              <div className="text-2xl md:text-3xl font-bold">{value}</div>
              <div className="text-xs opacity-80 mt-0.5">{label}</div>
            </div>
          ))}
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-3 gap-3">
        <Link to="/search" className="card p-4 text-center hover:shadow-md transition-shadow group">
          <Search className="w-6 h-6 text-blue-500 mx-auto mb-1.5 group-hover:scale-110 transition-transform" />
          <div className="text-xs font-medium text-gray-700">New Search</div>
        </Link>
        <Link to="/queue" className="card p-4 text-center hover:shadow-md transition-shadow group">
          <ListTodo className="w-6 h-6 text-yellow-500 mx-auto mb-1.5 group-hover:scale-110 transition-transform" />
          <div className="text-xs font-medium text-gray-700">Review Queue</div>
        </Link>
        <Link to="/applications" className="card p-4 text-center hover:shadow-md transition-shadow group">
          <TrendingUp className="w-6 h-6 text-green-500 mx-auto mb-1.5 group-hover:scale-110 transition-transform" />
          <div className="text-xs font-medium text-gray-700">Applications</div>
        </Link>
      </div>

      {/* Auto-Pilot panel */}
      <AutoPilotPanel />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Pipeline chart */}
        <div className="card p-5">
          <h2 className="font-semibold text-gray-900 mb-4">Pipeline</h2>
          {statsLoading ? (
            <div className="h-40 flex items-center justify-center">
              <div className="w-full h-full bg-gray-100 rounded-lg animate-pulse" />
            </div>
          ) : chartData.length === 0 ? (
            <div className="h-40 flex flex-col items-center justify-center text-gray-400 text-sm gap-2">
              <Search className="w-8 h-8 opacity-50" />
              <p>No applications yet.</p>
              <Link to="/search" className="text-tomato-600 hover:underline text-xs">
                Start a job search →
              </Link>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={chartData} barSize={28}>
                <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} allowDecimals={false} width={25} />
                <Tooltip
                  contentStyle={{
                    borderRadius: 8,
                    border: 'none',
                    boxShadow: '0 4px 20px rgba(0,0,0,0.1)',
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {chartData.map((entry) => (
                    <Cell key={entry.name} fill={CHART_COLORS[entry.name] || '#6b7280'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Job queue preview */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-gray-900">Jobs to Review</h2>
            <Link to="/queue" className="text-sm text-tomato-600 hover:underline flex items-center gap-1">
              All {queueCount > 0 && `(${queueCount})`} <ChevronRight className="w-3 h-3" />
            </Link>
          </div>
          {queueLoading ? (
            <div className="space-y-2">
              {Array(3).fill(0).map((_, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5">
                  <div className="w-8 h-8 rounded-lg bg-gray-200 animate-pulse" />
                  <div className="flex-1 space-y-1.5">
                    <div className="h-3 bg-gray-200 rounded animate-pulse w-3/4" />
                    <div className="h-2.5 bg-gray-100 rounded animate-pulse w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : !queueData?.jobs?.length ? (
            <div className="py-8 text-center text-gray-400 text-sm">
              <Search className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="mb-2">No jobs in queue.</p>
              <Link to="/search" className="text-tomato-600 hover:underline text-sm">
                Run a job search
              </Link>
            </div>
          ) : (
            <div className="space-y-1">
              {queueData.jobs.map((job) => (
                <Link
                  key={job.id}
                  to="/queue"
                  className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <div className="w-8 h-8 rounded-lg bg-tomato-100 flex items-center justify-center text-tomato-700 font-bold text-xs flex-shrink-0">
                    {job.company[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate">{job.title}</div>
                    <div className="text-xs text-gray-500 truncate">{job.company}</div>
                  </div>
                  <div className="text-xs text-tomato-600 font-medium flex-shrink-0">
                    {Math.round((job.relevance_score || 0) * 100)}%
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recent applications */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">Recent Applications</h2>
          <Link to="/applications" className="text-sm text-tomato-600 hover:underline flex items-center gap-1">
            View all <ChevronRight className="w-3 h-3" />
          </Link>
        </div>
        {appsLoading ? (
          <div className="space-y-1">
            {Array(3).fill(0).map((_, i) => (
              <div key={i} className="flex items-center gap-4 py-3">
                <div className="w-8 h-8 rounded-lg bg-gray-200 animate-pulse" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-3 bg-gray-200 rounded animate-pulse w-1/2" />
                  <div className="h-2.5 bg-gray-100 rounded animate-pulse w-1/3" />
                </div>
                <div className="h-5 w-16 bg-gray-100 rounded-full animate-pulse" />
              </div>
            ))}
          </div>
        ) : !recentApps?.length ? (
          <div className="py-6 text-center text-gray-400 text-sm">
            No applications yet. Approve jobs from the queue to start.
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {recentApps.map((app) => (
              <Link
                key={app.id}
                to={`/applications/${app.id}`}
                className="flex items-center gap-4 py-3 hover:bg-gray-50 -mx-1 px-1 rounded-lg transition-colors"
              >
                <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center text-gray-600 font-bold text-xs flex-shrink-0">
                  {(app.job?.company || '?')[0]}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-900 truncate">
                    {app.job?.title || 'Unknown Position'}
                  </div>
                  <div className="text-xs text-gray-500">{app.job?.company}</div>
                </div>
                <StatusBadge status={app.status} />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
