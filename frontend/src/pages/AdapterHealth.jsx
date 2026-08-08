import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  BellRing,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  ExternalLink,
  RefreshCw,
  SearchCheck,
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
      {normalized.replaceAll('_', ' ')}
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

function IncidentCard({ incident }) {
  const recovery = incident.recovery_path
  return (
    <div className={`rounded-xl border p-3 ${SEVERITY_STYLES[incident.severity] || SEVERITY_STYLES.warning}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold capitalize">
            {incident.domain} · {String(incident.entity || 'system').replaceAll('_', ' ')} · {String(incident.code || '').replaceAll('_', ' ')}
          </div>
          <div className="text-xs mt-1 opacity-90">{incident.detail}</div>
          {Array.isArray(incident.application_ids) && incident.application_ids.length > 0 && (
            <div className="text-[11px] mt-1.5 opacity-75">
              Applications: {incident.application_ids.join(', ')}
            </div>
          )}
          {recovery && (
            <Link to={recovery} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold underline underline-offset-2">
              Open recovery view <ExternalLink className="w-3 h-3" />
            </Link>
          )}
        </div>
        <span className="text-xs font-bold rounded-full bg-white/70 px-2 py-0.5">{incident.count}</span>
      </div>
    </div>
  )
}

export default function AdapterHealth() {
  const [windowHours, setWindowHours] = useState(24)
  const [syncMessage, setSyncMessage] = useState('')
  const qc = useQueryClient()
  const {
    data: report,
    error,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['operationalObservability', windowHours],
    queryFn: () => api.get('/adapter-health/observability', { params: { window_hours: windowHours } }),
    select: (response) => response.data,
    refetchInterval: 60_000,
  })

  const syncMutation = useMutation({
    mutationFn: () => api.post('/adapter-health/observability/notifications/refresh', null, { params: { window_hours: windowHours } }),
    onSuccess: (response) => {
      const data = response.data || {}
      setSyncMessage(`${data.notifications_created || 0} new incident alert(s), ${data.notifications_deduplicated || 0} deduplicated${data.digest_created ? ', digest created' : ''}.`)
      qc.invalidateQueries({ queryKey: ['notifications'] })
      qc.invalidateQueries({ queryKey: ['unreadCount'] })
      refetch()
    },
    onError: (syncError) => setSyncMessage(getApiErrorMessage(syncError, 'Alert refresh failed.')),
  })

  const adapter = report?.adapter_health || {}
  const adapterSummary = adapter?.summary || {}
  const platforms = adapter?.platforms || []
  const source = report?.source_health || {}
  const sources = source?.sources || []
  const sourceSummary = source?.summary || {}
  const incidents = report?.incidents || []
  const summary = report?.summary || {}
  const activity = report?.activity || {}

  const overallStatus = summary.critical_incident_count > 0
    ? 'critical'
    : summary.incident_count > 0
      ? 'degraded'
      : (platforms.length || sources.length) ? 'healthy' : 'no_data'

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl md:text-2xl font-bold text-gray-900">Operational Reliability</h1>
            {!isLoading && <StatusPill status={overallStatus} />}
          </div>
          <p className="text-gray-500 mt-1 text-sm">
            Source discovery, adapter outcomes, policy breakers, material integrity, and actionable incidents.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={windowHours}
            onChange={(event) => setWindowHours(Number(event.target.value))}
            className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700"
            aria-label="Reliability reporting window"
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
          <button
            type="button"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="inline-flex items-center gap-2 border border-gray-200 bg-white text-gray-800 rounded-lg px-3 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-60"
          >
            <BellRing className="w-4 h-4" />
            Sync alerts
          </button>
        </div>
      </div>

      {syncMessage && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">{syncMessage}</div>
      )}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          {getApiErrorMessage(error, 'Operational reliability could not be loaded.')}
        </div>
      )}

      {isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
          {Array(6).fill(0).map((_, index) => (
            <div key={index} className="h-28 rounded-2xl bg-gray-100 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
          <MetricCard icon={SearchCheck} label="Jobs saved" value={activity.new_jobs_saved ?? 0} />
          <MetricCard icon={Activity} label="Attempts" value={activity.application_attempts ?? 0} />
          <MetricCard icon={CheckCircle2} label="Confirmed" value={activity.confirmed ?? 0} />
          <MetricCard icon={Clock3} label="Manual review" value={activity.manual_review ?? 0} />
          <MetricCard icon={DatabaseZap} label="Source failures" value={sourceSummary.failures ?? 0} />
          <MetricCard icon={Siren} label="Incidents" value={summary.incident_count ?? 0} detail={`${summary.critical_incident_count ?? 0} critical`} />
        </div>
      )}

      <div className="card p-5">
        <div className="flex items-center justify-between mb-4 gap-3">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500" /> Active Incidents
          </h2>
          <span className="text-xs text-gray-400">
            {report?.generated_at ? `Updated ${new Date(report.generated_at).toLocaleString()}` : ''}
          </span>
        </div>
        {incidents.length === 0 ? (
          <div className="py-8 text-center">
            <ShieldCheck className="w-9 h-9 mx-auto text-emerald-500 mb-2" />
            <div className="text-sm font-medium text-gray-800">No active operational incidents</div>
            <div className="text-xs text-gray-500 mt-1">The selected reporting window is clear.</div>
          </div>
        ) : (
          <div className="space-y-2">
            {incidents.map((incident) => <IncidentCard key={incident.fingerprint} incident={incident} />)}
          </div>
        )}
      </div>

      <div className="card overflow-hidden">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <SearchCheck className="w-4 h-4 text-tomato-600" /> Discovery Source Health
          </h2>
          <span className="text-xs text-gray-400">{source.run_count ?? 0} discovery run(s)</span>
        </div>
        {sources.length === 0 ? (
          <div className="py-10 text-center text-sm text-gray-500">No source diagnostics were recorded in this window.</div>
        ) : (
          <div className="divide-y divide-gray-100">
            {sources.map((item) => (
              <div key={item.source} className="p-5">
                <div className="flex flex-col lg:flex-row lg:items-center gap-4">
                  <div className="lg:w-56 min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="font-semibold text-gray-900 capitalize">{item.source}</div>
                      <StatusPill status={item.status} />
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      {item.last_observed_at ? `Last observation ${new Date(item.last_observed_at).toLocaleString()}` : 'No observation time'}
                    </div>
                  </div>
                  <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 flex-1">
                    <div><div className="text-lg font-bold text-gray-900">{item.observations}</div><div className="text-[11px] text-gray-500">Checks</div></div>
                    <div><div className="text-lg font-bold text-emerald-600">{item.successful_observations}</div><div className="text-[11px] text-gray-500">Success</div></div>
                    <div><div className="text-lg font-bold text-red-600">{item.failed_observations}</div><div className="text-[11px] text-gray-500">Failed</div></div>
                    <div><div className="text-lg font-bold text-amber-600">{item.zero_result_observations}</div><div className="text-[11px] text-gray-500">Zero-result</div></div>
                    <div><div className="text-lg font-bold text-gray-900">{item.result_count}</div><div className="text-[11px] text-gray-500">Results</div></div>
                    <div><div className="text-lg font-bold text-gray-900"><Percent value={item.success_rate} /></div><div className="text-[11px] text-gray-500">Success rate</div></div>
                  </div>
                </div>
                {Object.keys(item.error_counts || {}).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {Object.entries(item.error_counts).map(([reason, count]) => (
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

      <div className="card overflow-hidden">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Activity className="w-4 h-4 text-tomato-600" /> Adapter Performance
          </h2>
          <span className="text-xs text-gray-400">Threshold: {adapter?.failure_threshold ?? 0}</span>
        </div>

        {platforms.length === 0 ? (
          <div className="py-10 text-center text-sm text-gray-500">No application attempts were recorded in this window.</div>
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
                    <div className="text-xs text-gray-500 mt-1">Maturity: {platform.maturity || 'unclassified'}</div>
                  </div>

                  <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 flex-1">
                    <div><div className="text-lg font-bold text-gray-900">{platform.attempts}</div><div className="text-[11px] text-gray-500">Attempts</div></div>
                    <div><div className="text-lg font-bold text-emerald-600">{platform.successful}</div><div className="text-[11px] text-gray-500">Successful</div></div>
                    <div><div className="text-lg font-bold text-amber-600">{platform.manual_review}</div><div className="text-[11px] text-gray-500">Review</div></div>
                    <div><div className="text-lg font-bold text-red-600">{platform.failed}</div><div className="text-[11px] text-gray-500">Failed</div></div>
                    <div><div className="text-lg font-bold text-gray-900"><Percent value={platform.success_rate} /></div><div className="text-[11px] text-gray-500">Success rate</div></div>
                    <div><div className="text-lg font-bold text-gray-900"><Percent value={platform.manual_review_rate} /></div><div className="text-[11px] text-gray-500">Review rate</div></div>
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

      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-xs text-blue-900 flex items-start gap-2">
        <ShieldAlert className="w-4 h-4 mt-0.5 flex-shrink-0" />
        <div>
          <div className="font-semibold">Evidence-only control surface</div>
          <div className="mt-1">Reliability reporting and alert synchronization cannot enable live submission, promote adapter maturity, retry an application, or send recruiter outreach.</div>
        </div>
      </div>
    </div>
  )
}
