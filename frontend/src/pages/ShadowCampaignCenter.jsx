import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileCheck2,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Square,
  TimerReset,
} from 'lucide-react'

import { getApiErrorMessage } from '../api/client'
import {
  getShadowCampaignPreflight,
  getShadowCampaigns,
  recordShadowCampaignEvidence,
  startShadowCampaign,
  stopShadowCampaign,
} from '../api/shadowCampaigns'

const TARGETS = [
  { value: 'shadow_run_4h', label: '4-hour campaign' },
  { value: 'shadow_run_8h', label: '8-hour campaign' },
  { value: 'shadow_run_24h', label: '24-hour campaign' },
]

const ACTIVE = new Set(['scheduled', 'running', 'settling', 'stopping'])

function humanize(value) {
  return String(value || '').replaceAll('_', ' ')
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds || 0))
  if (value >= 3600) return `${(value / 3600).toFixed(value % 3600 ? 1 : 0)}h`
  if (value >= 60) return `${Math.floor(value / 60)}m`
  return `${Math.floor(value)}s`
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

function shortHash(value) {
  return String(value || '').slice(0, 12) || '—'
}

function Progress({ measured, requested }) {
  const total = Math.max(1, Number(requested || 1))
  const current = Math.max(0, Number(measured || 0))
  const percent = Math.min(100, Math.round((current / total) * 100))
  return (
    <div>
      <div className="mb-1 flex justify-between text-[11px] text-gray-500">
        <span>{formatDuration(current)}</span>
        <span>{formatDuration(total)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-gray-100">
        <div className="h-full rounded-full bg-gray-900 transition-all" style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

function Metric({ label, value }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
      <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-gray-400">{label}</div>
      <div className="mt-1 text-lg font-black text-gray-900">{value}</div>
    </div>
  )
}

function SessionCard({ session }) {
  const queryClient = useQueryClient()
  const [stopAck, setStopAck] = useState('')
  const active = ACTIVE.has(session.status)
  const qualified = session.final_report?.qualification_eligible === true
  const expectedStop = session.expected_stop_acknowledgment || `STOP FULL STACK SHADOW ${session.session_id}`

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['shadow-campaigns'] })
    queryClient.invalidateQueries({ queryKey: ['certification-evidence'] })
    queryClient.invalidateQueries({ queryKey: ['certification-manifest'] })
  }
  const stop = useMutation({
    mutationFn: () => stopShadowCampaign(session.session_id, { acknowledgment: stopAck }),
    onSuccess: refresh,
  })
  const record = useMutation({
    mutationFn: () => recordShadowCampaignEvidence(session.session_id),
    onSuccess: refresh,
  })
  const error = stop.error || record.error

  return (
    <div className="card p-5 space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-bold text-gray-900">Campaign #{session.session_id}</span>
            <span className={`badge ${qualified ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : active ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-gray-300 bg-gray-50 text-gray-700'}`}>
              {humanize(session.status)}
            </span>
            {qualified && <span className="badge border-emerald-300 bg-emerald-50 text-emerald-700">qualified</span>}
          </div>
          <div className="mt-1 text-xs text-gray-500">
            {humanize(session.target_evidence_type)} · head {shortHash(session.candidate_revision)} · started {formatDate(session.started_at)}
          </div>
        </div>
        <div className="text-xs font-mono text-gray-400">{shortHash(session.report_sha256)}</div>
      </div>

      <Progress measured={session.measured_duration_seconds} requested={session.requested_duration_seconds} />

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        <Metric label="Cycles" value={`${session.cycles_completed}/${session.cycles_failed}`} />
        <Metric label="Applications" value={session.applications_created} />
        <Metric label="Ready" value={session.applications_ready_to_submit} />
        <Metric label="Human" value={session.human_boundaries} />
        <Metric label="Unexplained" value={session.unexplained_records} />
        <Metric label="Duplicates" value={session.duplicate_application_ids} />
        <Metric label="Runaway" value={session.runaway_retry_count} />
      </div>

      {session.status === 'settling' && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">
          Duration reached. The campaign is waiting for correlated dry-run work to settle before reconciliation. Deadline: {formatDate(session.settle_deadline_at)}.
        </div>
      )}
      {session.failure_reason && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">{session.failure_reason}</div>
      )}

      {session.final_report?.quality && (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(session.final_report.quality).map(([name, ok]) => (
            <div key={name} className="flex items-center gap-2 rounded-lg border border-gray-100 px-3 py-2 text-xs text-gray-700">
              {ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <AlertTriangle className="h-4 w-4 text-amber-600" />}
              <span>{humanize(name)}</span>
            </div>
          ))}
        </div>
      )}

      {active && (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
          <div className="text-xs font-bold text-gray-800">Exact stop acknowledgment</div>
          <code className="mt-2 block overflow-x-auto rounded-lg bg-white px-3 py-2 text-[11px] text-gray-700">{expectedStop}</code>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <input
              value={stopAck}
              onChange={(event) => setStopAck(event.target.value)}
              className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-mono"
              placeholder="Type the exact stop phrase"
            />
            <button
              type="button"
              disabled={stop.isPending || stopAck !== expectedStop}
              onClick={() => stop.mutate()}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-bold text-gray-800 disabled:opacity-50"
            >
              {stop.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />} Stop campaign
            </button>
          </div>
        </div>
      )}

      {!active && qualified && !session.certification_evidence_id && (
        <button
          type="button"
          disabled={record.isPending}
          onClick={() => record.mutate()}
          className="inline-flex items-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"
        >
          {record.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />}
          Record as unreviewed certification evidence
        </button>
      )}
      {session.certification_evidence_id && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
          Certification evidence #{session.certification_evidence_id} is retained as <strong>unreviewed</strong>. Independent verification remains a separate action in Certification Center.
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
          {getApiErrorMessage(error, 'Shadow campaign action was blocked.')}
        </div>
      )}
    </div>
  )
}

export default function ShadowCampaignCenter() {
  const queryClient = useQueryClient()
  const [target, setTarget] = useState('shadow_run_4h')
  const [ack, setAck] = useState('')
  const [intervalMinutes, setIntervalMinutes] = useState('15')

  const preflight = useQuery({
    queryKey: ['shadow-preflight', target],
    queryFn: () => getShadowCampaignPreflight(target),
    select: (response) => response.data,
  })
  const sessionsQuery = useQuery({
    queryKey: ['shadow-campaigns'],
    queryFn: () => getShadowCampaigns({ limit: 100 }),
    select: (response) => response.data,
    refetchInterval: (query) => {
      const rows = query.state.data?.sessions || []
      return rows.some((item) => ACTIVE.has(item.status)) ? 15_000 : 60_000
    },
  })
  const sessions = useMemo(() => sessionsQuery.data?.sessions || [], [sessionsQuery.data])
  const active = sessions.find((session) => ACTIVE.has(session.status))
  const expected = preflight.data?.expected_start_acknowledgment || ''

  const start = useMutation({
    mutationFn: () => startShadowCampaign({
      target_evidence_type: target,
      acknowledgment: ack,
      cycle_interval_seconds: Math.max(60, Math.round(Number(intervalMinutes || 15) * 60)),
    }),
    onSuccess: () => {
      setAck('')
      queryClient.invalidateQueries({ queryKey: ['shadow-campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['shadow-preflight'] })
    },
  })

  const error = preflight.error || sessionsQuery.error || start.error
  const checks = Object.entries(preflight.data?.checks || {})

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold text-gray-900 md:text-2xl">Shadow Campaign Center</h1>
            <span className="badge border-blue-300 bg-blue-50 text-blue-700">full-stack no-submit</span>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-gray-500">
            Exercise the real scheduler, discovery, preparation, human boundaries, reconciliation, and observability without permitting a final application submission.
          </p>
        </div>
        <button
          type="button"
          onClick={() => { preflight.refetch(); sessionsQuery.refetch() }}
          disabled={preflight.isFetching || sessionsQuery.isFetching}
          className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${(preflight.isFetching || sessionsQuery.isFetching) ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-700" />
          <div>
            <div className="text-sm font-bold text-emerald-900">No-submit evidence collection</div>
            <p className="mt-1 text-xs leading-5 text-emerald-800">
              The supervisor never enables real submission or recruiter outreach. A qualifying campaign can only create an unreviewed evidence record; certification review stays separate.
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.4fr]">
        <div className="card p-5 space-y-4">
          <div className="flex items-center gap-2"><TimerReset className="h-5 w-5 text-blue-600" /><h2 className="font-bold text-gray-900">Start a campaign</h2></div>
          <label className="block text-xs font-semibold text-gray-700">
            Evidence target
            <select value={target} onChange={(event) => { setTarget(event.target.value); setAck('') }} className="mt-1.5 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm">
              {TARGETS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label className="block text-xs font-semibold text-gray-700">
            Cycle interval in minutes
            <input type="number" min="1" max="60" value={intervalMinutes} onChange={(event) => setIntervalMinutes(event.target.value)} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" />
          </label>

          <div className="space-y-2">
            <div className="text-xs font-bold text-gray-800">Preflight</div>
            {checks.map(([name, ok]) => (
              <div key={name} className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 text-xs">
                <span className="text-gray-600">{humanize(name)}</span>
                {ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <AlertTriangle className="h-4 w-4 text-amber-600" />}
              </div>
            ))}
            {!checks.length && <div className="text-xs text-gray-400">Loading preflight…</div>}
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
            <div className="text-xs font-bold text-gray-800">Exact start acknowledgment</div>
            <code className="mt-2 block overflow-x-auto rounded-lg bg-white px-3 py-2 text-[11px] text-gray-700">{expected || 'Unavailable until preflight passes'}</code>
            <input value={ack} onChange={(event) => setAck(event.target.value)} className="mt-2 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-mono" placeholder="Type the exact phrase" />
          </div>

          <button
            type="button"
            disabled={start.isPending || !preflight.data?.ok || !expected || ack !== expected || Boolean(active)}
            onClick={() => start.mutate()}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"
          >
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Clock3 className="h-4 w-4" />}
            {active ? `Campaign #${active.session_id} already active` : 'Start full-stack shadow campaign'}
          </button>
        </div>

        <div className="card p-5">
          <h2 className="font-bold text-gray-900">What earns qualification</h2>
          <p className="mt-1 text-xs leading-5 text-gray-500">Time alone is insufficient. The retained report must pass every reconciliation gate.</p>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {[
              'Measured target duration',
              'At least one scheduler cycle',
              'Real discovery path observed',
              'Dry-run application path observed',
              'Zero failed campaign cycles',
              'Zero false submitted states',
              'Zero duplicate application references',
              'Zero runaway retries',
              'Zero unexplained failures',
              'No active work after settling',
              'No policy escape',
              'Exact candidate revision retained',
            ].map((label) => (
              <div key={label} className="flex items-center gap-2 rounded-xl border border-gray-100 bg-gray-50 p-3 text-xs text-gray-700">
                <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-gray-400" /> {label}
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-800">
            <strong>Settling is intentional.</strong> Once the requested duration is reached, no new scheduler cycle starts. Existing correlated dry-run work gets a bounded window to finish before the campaign is reconciled.
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {getApiErrorMessage(error, 'Shadow Campaign Center could not complete the request.')}
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <div><h2 className="font-bold text-gray-900">Campaign history</h2><p className="text-xs text-gray-500">Active campaigns poll every 15 seconds; retained history stays account-scoped.</p></div>
        {(preflight.isLoading || sessionsQuery.isLoading) && <Loader2 className="h-5 w-5 animate-spin text-gray-400" />}
      </div>
      <div className="space-y-4">
        {sessions.map((session) => <SessionCard key={session.session_id} session={session} />)}
        {!sessions.length && !sessionsQuery.isLoading && (
          <div className="card p-10 text-center text-sm text-gray-400">No full-stack shadow campaigns have been retained yet.</div>
        )}
      </div>
    </div>
  )
}
