import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  getApplicationStats,
  getJobQueue,
  listApplications,
  runAutoPilot,
  bulkApply,
  getOperationsReadiness,
  getAtsCertification,
} from '../api/client'
import { useAuthStore } from '../store'
import StatusBadge from '../components/StatusBadge'
import { StatCardSkeleton } from '../components/Skeleton'
import {
  TrendingUp, Briefcase, Clock, Award, ChevronRight,
  Search, Zap, ListTodo, Bot, Play, Send, Loader2,
  CheckCircle2, Activity, Rocket, ShieldCheck, ShieldOff,
  PauseCircle, Gauge, AlertTriangle,
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

function ControllerMetric({ icon: Icon, label, value, detail }) {
  return (
    <div className="rounded-xl bg-white/10 border border-white/10 p-3">
      <div className="flex items-center gap-1.5 text-white/70 text-[11px] uppercase tracking-wide">
        <Icon className="w-3.5 h-3.5" />
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-white">{value}</div>
      {detail && <div className="mt-0.5 text-[11px] text-white/60">{detail}</div>}
    </div>
  )
}

function AutoPilotPanel({ readiness, atsManifest, isLoading }) {
  const qc = useQueryClient()
  const [msg, setMsg] = useState(null)
  const [msgType, setMsgType] = useState('info')

  const adapters = atsManifest?.adapters || []
  const autonomousAdapters = adapters.filter((adapter) =>
    adapter?.maturity === 'certified_autonomous' ||
    adapter?.certification_level === 'certified_autonomous'
  )
  const dailyCap = readiness?.defaults?.daily_cap ?? '—'
  const weeklyCap = readiness?.defaults?.weekly_cap ?? '—'
  const disabledPlatforms = readiness?.disabled_platforms || []

  const pilotMut = useMutation({
    mutationFn: () => runAutoPilot({ min_score: 0.55, daily_limit: 15 }),
    onSuccess: (res) => {
      const d = res.data
      setMsgType('success')
      setMsg(
        `Preview run launched: ${d.auto_approved} jobs approved and ` +
        `${d.applications_queued ?? 0} applications queued for preparation.`
      )
      qc.invalidateQueries({ queryKey: ['jobQueue'] })
      qc.invalidateQueries({ queryKey: ['appStats'] })
      qc.invalidateQueries({ queryKey: ['recentApps'] })
    },
    onError: (e) => {
      setMsgType('error')
      setMsg('Controller error: ' + (e.response?.data?.detail || e.message))
    },
  })

  const bulkMut = useMutation({
    mutationFn: () => bulkApply(true, 20),
    onSuccess: (res) => {
      const d = res.data
      setMsgType('success')
      setMsg(`Preview preparation: ${d.applied} applications queued, ${d.skipped} already existed.`)
      qc.invalidateQueries({ queryKey: ['appStats'] })
      qc.invalidateQueries({ queryKey: ['recentApps'] })
    },
    onError: (e) => {
      setMsgType('error')
      setMsg('Controller error: ' + (e.response?.data?.detail || e.message))
    },
  })

  const running = pilotMut.isPending || bulkMut.isPending

  return (
    <div className="rounded-2xl p-5 bg-gradient-to-br from-slate-900 via-slate-800 to-rose-950 text-white shadow-lg">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center flex-shrink-0">
          <Rocket className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="font-bold text-lg">Automation Controller</h2>
            <span className="text-[11px] bg-amber-400/15 text-amber-200 border border-amber-300/20 px-2 py-0.5 rounded-full">
              Progressive autonomy
            </span>
          </div>
          <p className="text-white/65 text-xs mt-0.5">
            Search, score, prepare, validate, and advance application paths according to the active release profile.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 mb-4">
        <ControllerMetric
          icon={readiness?.autopilot_enabled ? ShieldCheck : PauseCircle}
          label="Scheduled autopilot"
          value={isLoading ? 'Checking…' : readiness?.autopilot_enabled ? 'Enabled' : 'Staged'}
          detail="Current operations profile"
        />
        <ControllerMetric
          icon={readiness?.real_submission_enabled ? ShieldCheck : ShieldOff}
          label="Live submission"
          value={isLoading ? 'Checking…' : readiness?.real_submission_enabled ? 'Enabled' : 'Staged'}
          detail="Promoted by release profile"
        />
        <ControllerMetric
          icon={Gauge}
          label="Application caps"
          value={`${dailyCap} daily / ${weeklyCap} weekly`}
          detail="Configured operating limits"
        />
        <ControllerMetric
          icon={autonomousAdapters.length ? ShieldCheck : AlertTriangle}
          label="Autonomous adapters"
          value={`${autonomousAdapters.length} / ${adapters.length || 5}`}
          detail="Progress toward certified_autonomous"
        />
      </div>

      {disabledPlatforms.length > 0 && (
        <div className="mb-4 text-xs px-3 py-2 rounded-lg bg-white/10 border border-white/10">
          Platforms excluded by this profile: <span className="font-semibold">{disabledPlatforms.join(', ')}</span>
        </div>
      )}

      <div className="flex flex-wrap gap-2.5">
        <button
          onClick={() => pilotMut.mutate()}
          disabled={running}
          className="flex items-center gap-2 bg-white text-slate-900 font-semibold text-sm px-4 py-2.5 rounded-xl hover:bg-slate-100 transition-all disabled:opacity-60 shadow-sm"
        >
          {pilotMut.isPending
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <Play className="w-4 h-4" />}
          Run Preview Pipeline
        </button>
        <button
          onClick={() => bulkMut.mutate()}
          disabled={running}
          className="flex items-center gap-2 bg-white/10 hover:bg-white/15 text-white font-semibold text-sm px-4 py-2.5 rounded-xl transition-all disabled:opacity-60 border border-white/15"
        >
          {bulkMut.isPending
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <Send className="w-4 h-4" />}
          Prepare Approved Jobs
        </button>
      </div>

      <p className="mt-3 text-[11px] text-white/55">
        This panel reflects the active release profile. Adapter promotion and real submission are governed by backend policy and certification evidence.
      </p>

      {msg && (
        <div className={`mt-3 text-xs px-3 py-2 rounded-lg ${
          msgType === 'success' ? 'bg-emerald-400/15 text-emerald-100' : 'bg-red-500/20 text-red-100'
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

  const { data: readiness, isLoading: readinessLoading } = useQuery({
    queryKey: ['operationsReadiness'],
    queryFn: () => getOperationsReadiness(),
    select: (r) => r.data,
    refetchInterval: 60000,
  })

  const { data: atsManifest, isLoading: atsLoading } = useQuery({
    queryKey: ['atsCertification'],
    queryFn: () => getAtsCertification(),
    select: (r) => r.data,
    staleTime: 60000,
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
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold text-gray-900">
            {user?.full_name ? `Hey ${user.full_name.split(' ')[0]}!` : 'Dashboard'}
          </h1>
          <p className="text-gray-500 mt-0.5 text-sm">
            Controller connected. JobTomatik is progressing from supervised foundation to autonomous operation.
          </p>
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

      <AutoPilotPanel
        readiness={readiness}
        atsManifest={atsManifest}
        isLoading={readinessLoading || atsLoading}
      />

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
              <p className="mb-2">Queue empty. Run a preview pipeline or manual search.</p>
              <Link to="/search" className="text-tomato-600 hover:underline text-sm">
                Run a manual search
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
            No applications yet. Run a <span className="text-tomato-600 font-medium">preview pipeline</span> above to prepare the system.
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
