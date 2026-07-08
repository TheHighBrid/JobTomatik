import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getApplicationStats, getJobQueue, listApplications, runAutoPilot, bulkApply } from '../api/client'
import { useAuthStore } from '../store'
import StatusBadge from '../components/StatusBadge'
import { StatCardSkeleton } from '../components/Skeleton'
import {
  TrendingUp, Briefcase, Clock, Award, ChevronRight,
  Search, Zap, ListTodo, Bot, Play, Send, Loader2,
  CheckCircle2, Activity, Rocket
} from 'lucide-react'
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
  const [msg, setMsg] = useState(null)
  const [msgType, setMsgType] = useState('info')

  const pilotMut = useMutation({
    mutationFn: () => runAutoPilot({ dry_run: false, min_score: 0.55, daily_limit: 15 }),
    onSuccess: (res) => {
      const d = res.data
      setMsgType('success')
      setMsg(
        `Pipeline launched: ${d.auto_approved} jobs auto-approved, ` +
        `${d.applications_queued ?? 0} applications queued for submission.`
      )
      qc.invalidateQueries(['jobQueue'])
      qc.invalidateQueries(['appStats'])
      qc.invalidateQueries(['recentApps'])
    },
    onError: (e) => {
      setMsgType('error')
      setMsg('Auto-pilot error: ' + (e.response?.data?.detail || e.message))
    },
  })

  const bulkMut = useMutation({
    mutationFn: () => bulkApply(false, 20),
    onSuccess: (res) => {
      const d = res.data
      setMsgType('success')
      setMsg(`Bulk apply: ${d.applied} applications queued, ${d.skipped} already submitted.`)
      qc.invalidateQueries(['appStats'])
      qc.invalidateQueries(['recentApps'])
    },
    onError: (e) => {
      setMsgType('error')
      setMsg('Bulk apply error: ' + (e.response?.data?.detail || e.message))
    },
  })

  const running = pilotMut.isPending || bulkMut.isPending

  return (
    <div className="rounded-2xl p-5 bg-gradient-to-br from-tomato-600 to-rose-700 text-white shadow-lg">
      <div className="flex items-center gap-2 mb-1">
        <Rocket className="w-5 h-5" />
        <h2 className="font-bold text-lg">Auto-Pilot</h2>
        <span className="ml-auto text-xs bg-white/20 px-2 py-0.5 rounded-full">Fully Autonomous</span>
      </div>
      <p className="text-white/75 text-xs mb-4">
        Search → approve → generate cover letter → submit. All automatic.
      </p>

      <div className="flex flex-wrap gap-2.5">
        <button
          onClick={() => pilotMut.mutate()}
          disabled={running}
          className="flex items-center gap-2 bg-white text-tomato-700 font-semibold text-sm px-4 py-2.5 rounded-xl hover:bg-tomato-50 transition-all disabled:opacity-60 shadow-sm"
        >
          {pilotMut.isPending
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <Play className="w-4 h-4" />}
          Full Auto-Pilot
        </button>
        <button
          onClick={() => bulkMut.mutate()}
          disabled={running}
          className="flex items-center gap-2 bg-white/15 hover:bg-white/25 text-white font-semibold text-sm px-4 py-2.5 rounded-xl transition-all disabled:opacity-60 border border-white/20"
        >
          {bulkMut.isPending
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <Send className="w-4 h-4" />}
          Bulk Apply Approved
        </button>
      </div>

      {msg && (
        <div className={`mt-3 text-xs px-3 py-2 rounded-lg ${
          msgType === 'success' ? 'bg-white/20' : 'bg-red-900/40'
        }`}>
          {msgType === 'success' && <CheckCircle2 className="w-3.5 h-3.5 inline mr-1" />}
          {msg}
        </div>
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
            {user?.full_name ? `Hey ${user.full_name.split(' ')[0]}!` : 'Dashboard'}
          </h1>
          <p className="text-gray-500 mt-0.5 text-sm">Your autonomous job search is active.</p>
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

      {/* Auto-Pilot (hero position) */}
      <AutoPilotPanel />

      {/* Stats grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {statsLoading
          ? Array(4).fill(0).map((_, i) => <StatCardSkeleton key={i} />)
          : topStats.map(({ label, value, icon: Icon, color }) => (
            <div key={label} className={`rounded-2xl p-4 bg-gradient-to-br ${color} text-white`}>
              <Icon className="w-5 h-5 opacity-80 mb-2" />
              <div className="text-2xl md:text-3xl font-bold">{value}</div>
              <div className="text-xs opacity-80 mt-0.5">{label}</div>
            </div>
          ))}
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { to: '/search', icon: Search, label: 'New Search', color: 'text-blue-500' },
          { to: '/queue', icon: ListTodo, label: 'Review Queue', color: 'text-yellow-500' },
          { to: '/applications', icon: Activity, label: 'Pipeline', color: 'text-green-500' },
        ].map(({ to, icon: Icon, label, color }) => (
          <Link
            key={to}
            to={to}
            className="card p-4 text-center hover:shadow-md transition-all group hover:-translate-y-0.5"
          >
            <Icon className={`w-6 h-6 ${color} mx-auto mb-1.5 group-hover:scale-110 transition-transform`} />
            <div className="text-xs font-medium text-gray-700">{label}</div>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Pipeline chart */}
        <div className="card p-5">
          <h2 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Activity className="w-4 h-4 text-tomato-600" /> Pipeline
          </h2>
          {statsLoading ? (
            <div className="h-40 bg-gray-100 rounded-lg animate-pulse" />
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
                    borderRadius: 10,
                    border: 'none',
                    boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="value" radius={[6, 6, 0, 0]}>
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
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Zap className="w-4 h-4 text-yellow-500" /> Jobs to Review
            </h2>
            <Link to="/queue" className="text-sm text-tomato-600 hover:underline flex items-center gap-1">
              All {queueCount > 0 && `(${queueCount})`} <ChevronRight className="w-3 h-3" />
            </Link>
          </div>
          {queueLoading ? (
            <div className="space-y-2">
              {Array(3).fill(0).map((_, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5">
                  <div className="w-8 h-8 rounded-xl bg-gray-200 animate-pulse" />
                  <div className="flex-1 space-y-1.5">
                    <div className="h-3 bg-gray-200 rounded animate-pulse w-3/4" />
                    <div className="h-2.5 bg-gray-100 rounded animate-pulse w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : !queueData?.jobs?.length ? (
            <div className="py-8 text-center text-gray-400 text-sm">
              <Bot className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="mb-2">Queue empty — auto-pilot will fill it.</p>
              <Link to="/search" className="text-tomato-600 hover:underline text-sm">
                Or run a manual search
              </Link>
            </div>
          ) : (
            <div className="space-y-1">
              {queueData.jobs.map((job) => (
                <Link
                  key={job.id}
                  to="/queue"
                  className="flex items-center gap-3 p-2.5 rounded-xl hover:bg-gray-50 transition-colors"
                >
                  <div className="w-8 h-8 rounded-xl bg-tomato-100 flex items-center justify-center text-tomato-700 font-bold text-xs flex-shrink-0">
                    {(job.company || '?')[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate">{job.title}</div>
                    <div className="text-xs text-gray-500 truncate">{job.company}</div>
                  </div>
                  <div className="text-xs font-bold text-tomato-600 flex-shrink-0 bg-tomato-50 px-2 py-0.5 rounded-full">
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
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-indigo-500" /> Recent Applications
          </h2>
          <Link to="/applications" className="text-sm text-tomato-600 hover:underline flex items-center gap-1">
            View all <ChevronRight className="w-3 h-3" />
          </Link>
        </div>
        {appsLoading ? (
          <div className="space-y-1">
            {Array(3).fill(0).map((_, i) => (
              <div key={i} className="flex items-center gap-4 py-3">
                <div className="w-8 h-8 rounded-xl bg-gray-200 animate-pulse" />
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
            No applications yet. Hit <span className="text-tomato-600 font-medium">Full Auto-Pilot</span> above to start.
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {recentApps.map((app) => (
              <Link
                key={app.id}
                to={`/applications/${app.id}`}
                className="flex items-center gap-4 py-3 hover:bg-gray-50 -mx-1 px-1 rounded-xl transition-colors"
              >
                <div className="w-8 h-8 rounded-xl bg-gray-100 flex items-center justify-center text-gray-600 font-bold text-xs flex-shrink-0">
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
