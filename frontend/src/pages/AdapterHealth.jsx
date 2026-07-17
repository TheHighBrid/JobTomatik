import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Siren,
} from 'lucide-react'
import api, { getApiErrorMessage } from '../api/client'


const STATUS_STYLES = {
  healthy: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  degraded: 'bg-amber-50 text-amber-700 border-amber-200',
  critical: 'bg-red-50 text-red-700 border-red-200',
  no_data: 'bg-gray-50 text-gray-600 border-gray-200',
}

const SEVERITY_STYLES = {
  critical: 'bg-red-50 text-red-800 border-red-200',
  warning: 'bg-amber-50 text-amber-800 border-amber-200',
}

function StatusPill({ status }) {
  const normalized = status || 'no_data'
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-semibold ${STATUS_STYLES[normalized] || STATUS_STYLES.no_data}`}>
      {normalized.replace('_', ' ')}
    </span>
  )
}

function MetricCard({ icon: Icon, label, value, detail }) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
        <Icon className="w-4 h-4" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-bold text-gray-900">{value}</div>
      {detail && <div className="mt-1 text-xs text-gray-500">{detail}</div>}
    </div>
  )
}

function Percent({ value }) {
  return <span>{Math.round((Number(value) || 0) * 100)}%</span>
}

export default function AdapterHealth() {
  const [windowHours, setWindowHours] = useState(24)
  const {
    data: health,
    error,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['adapterHealth', windowHours],
    queryFn: () => api.get('/adapter-health', { params: { window_hours: windowHours } }),
    select: (response) => response.data,
    refetchInterval: 60_000,
  })

  const summary = health?.summary || {}
  const platforms = health?.platforms || []
  const alerts = health?.alerts || []

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl md:text-2xl font-bold text-gray-900">Adapter Health</h1>
            {!isLoading && <StatusPill status={summary.status} />}
          </div>
          <p className="text-gray-500 mt-1 text-sm">
            Operational evidence from application attempts, handoffs, and confirmation outcomes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={windowHours}
            onChange={(event) => setWindowHours(Number(event.target.value))}
            className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700"
            aria-label="Health reporting window"
          >
            <option value={24}>Last 24 hours</option>
            <option value={72}>Last 3 days</option>
            <option value={168}>Last 7 days</option>
            <option value={720}>Last 30 days</option>
          </select>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-2 bg-gray-900 text-white rounded-lg px-3 py-2 text-sm font-medium hover:bg-gray-800 disabled:opacity-60"
          >
            <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          {getApiErrorMessage(error, 'Adapter health could not be loaded.')}
        </div>
      )}

      {isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {Array(5).fill(0).map((_, index) => (
            <div key={index} className="h-28 rounded-2xl bg-gray-100 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <MetricCard icon={Activity} label="Attempts" value={summary.attempts ?? 0} />
          <MetricCard icon={CheckCircle2} label="Successful" value={summary.successful ?? 0} detail={`${summary.confirmed ?? 0} confirmed`} />
          <MetricCard icon={Clock3} label="Manual review" value={summary.manual_review ?? 0} />
          <MetricCard icon={ShieldAlert} label="Uncertain" value={summary.submission_uncertain ?? 0} />
          <MetricCard icon={Siren} label="Active alerts" value={summary.alert_count ?? 0} detail={`${summary.critical_alert_count ?? 0} critical`} />
        </div>
      )}

      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500" /> Active Alerts
          </h2>
          <span className="text-xs text-gray-400">
            Threshold: {health?.failure_threshold ?? 0}
          </span>
        </div>
        {alerts.length === 0 ? (
          <div className="py-8 text-center">
            <ShieldCheck className="w-9 h-9 mx-auto text-emerald-500 mb-2" />
            <div className="text-sm font-medium text-gray-800">No active adapter alerts</div>
            <div className="text-xs text-gray-500 mt-1">The selected reporting window is clear.</div>
          </div>
        ) : (
          <div className="space-y-2">
            {alerts.map((alert, index) => (
              <div
                key={`${alert.platform}-${alert.code}-${index}`}
                className={`rounded-xl border p-3 ${SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.warning}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold capitalize">
                      {alert.platform} · {String(alert.code || '').replaceAll('_', ' ')}
                    </div>
                    <div className="text-xs mt-1 opacity-90">{alert.detail}</div>
                  </div>
                  <span className="text-xs font-bold rounded-full bg-white/70 px-2 py-0.5">
                    {alert.count}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card overflow-hidden">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Activity className="w-4 h-4 text-tomato-600" /> Platform Performance
          </h2>
          {health?.generated_at && (
            <span className="text-xs text-gray-400">
              Updated {new Date(health.generated_at).toLocaleString()}
            </span>
          )}
        </div>

        {platforms.length === 0 ? (
          <div className="py-10 text-center text-sm text-gray-500">
            No application attempts were recorded in this window.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {platforms.map((platform) => (
              <div key={platform.platform} className="p-5">
                <div className="flex flex-col lg:flex-row lg:items-center gap-4">
                  <div className="lg:w-56 min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="font-semibold text-gray-900 capitalize">{platform.platform}</div>
                      <StatusPill status={platform.status} />
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      Maturity: {platform.maturity || 'unclassified'}
                    </div>
                  </div>

                  <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 flex-1">
                    <div>
                      <div className="text-lg font-bold text-gray-900">{platform.attempts}</div>
                      <div className="text-[11px] text-gray-500">Attempts</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-emerald-600">{platform.successful}</div>
                      <div className="text-[11px] text-gray-500">Successful</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-amber-600">{platform.manual_review}</div>
                      <div className="text-[11px] text-gray-500">Review</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-red-600">{platform.failed}</div>
                      <div className="text-[11px] text-gray-500">Failed</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-gray-900"><Percent value={platform.success_rate} /></div>
                      <div className="text-[11px] text-gray-500">Success rate</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-gray-900"><Percent value={platform.manual_review_rate} /></div>
                      <div className="text-[11px] text-gray-500">Review rate</div>
                    </div>
                  </div>
                </div>

                {Object.keys(platform.reason_counts || {}).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {Object.entries(platform.reason_counts).map(([reason, count]) => (
                      <span key={reason} className="text-[11px] bg-gray-100 text-gray-600 rounded-full px-2 py-1">
                        {reason.replaceAll('_', ' ')}: {count}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <p className="text-[11px] text-gray-400 text-center">
        This view reports evidence only. It cannot enable live submission or change adapter maturity.
      </p>
    </div>
  )
}
