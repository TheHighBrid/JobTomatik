import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getApplicationStats, getJobQueue, listApplications } from '../api/client'
import { useAuthStore } from '../store'
import StatusBadge from '../components/StatusBadge'
import { TrendingUp, Briefcase, Clock, Award, ChevronRight, Search } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const STAT_COLORS = {
  total: 'from-blue-500 to-blue-600',
  applied: 'from-indigo-500 to-indigo-600',
  interviewing: 'from-purple-500 to-purple-600',
  offer: 'from-green-500 to-green-600',
}

const CHART_COLORS = {
  pending: '#9ca3af',
  applied: '#6366f1',
  interviewing: '#a855f7',
  offer: '#22c55e',
  rejected: '#ef4444',
}

export default function Dashboard() {
  const { user } = useAuthStore()

  const { data: stats } = useQuery({
    queryKey: ['appStats'],
    queryFn: () => getApplicationStats(),
    select: (r) => r.data,
  })

  const { data: queueData } = useQuery({
    queryKey: ['jobQueue', { per_page: 5 }],
    queryFn: () => getJobQueue({ per_page: 5 }),
    select: (r) => r.data,
  })

  const { data: recentApps } = useQuery({
    queryKey: ['recentApps'],
    queryFn: () => listApplications({ per_page: 5 }),
    select: (r) => r.data,
  })

  const chartData = stats
    ? Object.entries(stats)
        .filter(([k]) => !['total'].includes(k))
        .map(([key, value]) => ({ name: key, value }))
        .filter((d) => d.value > 0)
    : []

  const topStats = [
    { label: 'Total Applications', value: stats?.total ?? 0, icon: Briefcase, gradient: STAT_COLORS.total },
    { label: 'Applied', value: stats?.applied ?? 0, icon: TrendingUp, gradient: STAT_COLORS.applied },
    { label: 'Interviewing', value: stats?.interviewing ?? 0, icon: Clock, gradient: STAT_COLORS.interviewing },
    { label: 'Offers', value: stats?.offer ?? 0, icon: Award, gradient: STAT_COLORS.offer },
  ]

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Greeting */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">
          Good morning{user?.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}!
        </h1>
        <p className="text-gray-500 mt-1">Here's your job search overview.</p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {topStats.map(({ label, value, icon: Icon, gradient }) => (
          <div key={label} className={`card p-4 bg-gradient-to-br ${gradient} text-white`}>
            <Icon className="w-5 h-5 opacity-80 mb-3" />
            <div className="text-3xl font-bold">{value}</div>
            <div className="text-sm opacity-80 mt-1">{label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Chart */}
        <div className="card p-5">
          <h2 className="font-semibold text-gray-900 mb-4">Application Pipeline</h2>
          {chartData.length === 0 ? (
            <div className="h-40 flex items-center justify-center text-gray-400 text-sm">
              No applications yet.{' '}
              <Link to="/search" className="ml-1 text-tomato-600 hover:underline">Start searching</Link>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={chartData} barSize={32}>
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip contentStyle={{ borderRadius: 8, border: 'none', boxShadow: '0 4px 20px rgba(0,0,0,0.1)' }} />
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
              View all <ChevronRight className="w-3 h-3" />
            </Link>
          </div>
          {!queueData?.jobs?.length ? (
            <div className="py-8 text-center text-gray-400 text-sm">
              <Search className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No jobs in queue.</p>
              <Link to="/search" className="text-tomato-600 hover:underline text-sm mt-1 block">
                Run a job search
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
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
                  <div className="text-xs text-gray-400 flex-shrink-0">
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
        {!recentApps?.length ? (
          <div className="py-6 text-center text-gray-400 text-sm">
            No applications yet.
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
