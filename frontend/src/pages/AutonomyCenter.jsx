import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  Activity,
  AlertTriangle,
  Ban,
  BookOpenCheck,
  CheckCircle2,
  ChevronRight,
  CircleGauge,
  Clock3,
  Database,
  Loader2,
  OctagonPause,
  Play,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Signal,
  SignalZero,
  Square,
  TimerReset,
  Unplug,
  UsersRound,
} from 'lucide-react'

import { getApiErrorMessage } from '../api/client'
import {
  drainAutonomyQueue,
  getAutonomyControlSnapshot,
  pauseAutonomy,
  rejectAutonomyApplication,
  resumeAutonomy,
} from '../api/autonomy'

function toneFor(value) {
  const normalized = String(value || '').toLowerCase()
  if (['running', 'ready', 'verified', 'confirmed', 'healthy', 'certified_autonomous'].includes(normalized)) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  }
  if (['paused', 'draining', 'needs_review', 'awaiting_user', 'submission_uncertain'].includes(normalized)) {
    return 'border-amber-200 bg-amber-50 text-amber-700'
  }
  if (['failed', 'blocked', 'invalid', 'open'].includes(normalized)) {
    return 'border-red-200 bg-red-50 text-red-700'
  }
  return 'border-gray-200 bg-gray-50 text-gray-600'
}

function Pill({ children, value }) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${toneFor(value || children)}`}>
      {children}
    </span>
  )
}

function Panel({ title, icon: Icon, count, children, action }) {
  return (
    <section className="card p-4 sm:p-5" aria-labelledby={`autonomy-${title.toLowerCase().replaceAll(' ', '-')}`}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="brand-icon-well h-9 w-9 flex-shrink-0"><Icon className="h-4 w-4" aria-hidden="true" /></span>
          <div className="min-w-0">
            <h2 id={`autonomy-${title.toLowerCase().replaceAll(' ', '-')}`} className="truncate text-sm font-bold text-gray-900 sm:text-base">{title}</h2>
            {count !== undefined && <p className="text-xs text-gray-500">{count}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

function Metric({ label, value, detail, icon: Icon }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-3.5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="brand-icon-well h-8 w-8"><Icon className="h-4 w-4" aria-hidden="true" /></span>
        <span className="text-lg font-extrabold text-gray-900">{value}</span>
      </div>
      <p className="mt-2 text-xs font-semibold text-gray-900">{label}</p>
      {detail && <p className="mt-0.5 text-[11px] text-gray-500">{detail}</p>}
    </div>
  )
}

function Empty({ children }) {
  return <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-center text-xs text-gray-500">{children}</div>
}

export default function AutonomyCenter() {
  const queryClient = useQueryClient()
  const [online, setOnline] = useState(() => typeof navigator === 'undefined' || navigator.onLine)

  const snapshotQuery = useQuery({
    queryKey: ['autonomy-control'],
    queryFn: getAutonomyControlSnapshot,
    select: (response) => response.data,
    enabled: online,
    refetchInterval: online ? 15_000 : false,
    retry: online ? 2 : false,
  })

  useEffect(() => {
    const handleOnline = () => {
      setOnline(true)
      queryClient.invalidateQueries({ queryKey: ['autonomy-control'] })
    }
    const handleOffline = () => setOnline(false)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [queryClient])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['autonomy-control'] })
  const mutationOptions = (successMessage) => ({
    onSuccess: () => {
      toast.success(successMessage)
      refresh()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Control action was blocked')),
  })

  const pauseMutation = useMutation({ mutationFn: () => pauseAutonomy(), ...mutationOptions('Autonomy paused') })
  const drainMutation = useMutation({ mutationFn: () => drainAutonomyQueue(), ...mutationOptions('Queue is draining') })
  const resumeMutation = useMutation({ mutationFn: () => resumeAutonomy(), ...mutationOptions('Autonomy resumed') })
  const rejectMutation = useMutation({
    mutationFn: ({ applicationId, title }) => rejectAutonomyApplication(applicationId, `Rejected from autonomy queue: ${title}`),
    ...mutationOptions('Application removed from autonomy queue'),
  })

  const data = snapshotQuery.data
  const mode = data?.operator_control?.mode || 'unknown'
  const mutationPending = pauseMutation.isPending || drainMutation.isPending || resumeMutation.isPending || rejectMutation.isPending
  const queueItems = data?.queue?.items || []
  const rejectableCount = useMemo(() => queueItems.filter((item) => item.can_reject).length, [queueItems])

  if (snapshotQuery.isLoading && !data) {
    return <div className="flex justify-center py-24"><Loader2 className="h-8 w-8 animate-spin text-tomato-500" aria-label="Loading autonomy control centre" /></div>
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="section-kicker">Day 34 · Android operations</p>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-gray-900 sm:text-3xl">Autonomy Control</h1>
          <p className="mt-2 max-w-3xl text-sm text-gray-500">
            One mobile surface for readiness, adapter eligibility, caps, queue state, blockers, handoffs, retained evidence, and operator kill controls.
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary inline-flex items-center justify-center gap-2 self-start"
          onClick={() => snapshotQuery.refetch()}
          disabled={!online || snapshotQuery.isFetching}
          aria-label="Refresh autonomy control status"
        >
          <RefreshCw className={`h-4 w-4 ${snapshotQuery.isFetching ? 'animate-spin' : ''}`} aria-hidden="true" />
          Refresh
        </button>
      </div>

      <div
        className={`rounded-2xl border p-4 ${online ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'}`}
        role="status"
        aria-live="polite"
      >
        <div className="flex items-start gap-3">
          {online ? <Signal className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-700" aria-hidden="true" /> : <SignalZero className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-700" aria-hidden="true" />}
          <div>
            <p className={`text-sm font-bold ${online ? 'text-emerald-900' : 'text-amber-900'}`}>{online ? 'Connected to control plane' : 'Offline: controls are read-only'}</p>
            <p className={`mt-0.5 text-xs ${online ? 'text-emerald-700' : 'text-amber-800'}`}>
              {online ? 'Status refreshes automatically. Reconnect also triggers an immediate refresh.' : 'No mutation is sent while offline. The last loaded snapshot remains visible for reference.'}
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
        <div className="flex gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-blue-700" aria-hidden="true" />
          <div className="text-sm text-blue-900">
            <p className="font-bold">No direct live-submit control.</p>
            <p className="mt-1 text-xs text-blue-800">Pause, drain, resume, and reject can only constrain or remove work. Submission still requires the certified adapter, policy, evidence, idempotency, challenge, and confirmation gates.</p>
          </div>
        </div>
      </div>

      <section className="card p-4 sm:p-5" aria-labelledby="autonomy-operator-controls">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Operator mode</p>
            <div className="mt-1 flex items-center gap-2">
              <h2 id="autonomy-operator-controls" className="text-xl font-extrabold capitalize text-gray-900">{mode}</h2>
              <Pill value={mode}>{mode}</Pill>
            </div>
            <p className="mt-1 text-xs text-gray-500">
              {mode === 'paused' && 'New admission and pre-browser execution are blocked.'}
              {mode === 'draining' && 'New admission is blocked; already-created work may finish through normal safety gates.'}
              {mode === 'running' && 'New admission is allowed only when every existing policy and certification gate also passes.'}
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap">
            <button
              type="button"
              className="btn-secondary inline-flex min-h-11 items-center justify-center gap-1.5 px-3"
              onClick={() => pauseMutation.mutate()}
              disabled={!online || mutationPending || mode === 'paused'}
              aria-label="Pause autonomous processing"
            >
              <OctagonPause className="h-4 w-4" aria-hidden="true" /> Pause
            </button>
            <button
              type="button"
              className="btn-secondary inline-flex min-h-11 items-center justify-center gap-1.5 px-3"
              onClick={() => drainMutation.mutate()}
              disabled={!online || mutationPending || mode === 'draining'}
              aria-label="Drain autonomy queue without admitting new work"
            >
              <TimerReset className="h-4 w-4" aria-hidden="true" /> Drain
            </button>
            <button
              type="button"
              className="btn-primary inline-flex min-h-11 items-center justify-center gap-1.5 px-3"
              onClick={() => resumeMutation.mutate()}
              disabled={!online || mutationPending || mode === 'running'}
              aria-label="Resume autonomous processing under existing safety gates"
            >
              <Play className="h-4 w-4" aria-hidden="true" /> Resume
            </button>
          </div>
        </div>
      </section>

      {!data && snapshotQuery.isError && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-800" role="alert">
          Control snapshot could not be loaded. No control mutation is available until the control plane reconnects.
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label="Readiness" value={data.readiness?.ready_for_new_admission ? 'Ready' : 'Blocked'} detail={String(data.readiness?.scheduler_state || 'unknown').replaceAll('_', ' ')} icon={CircleGauge} />
            <Metric label="Eligible adapters" value={`${data.readiness?.eligible_enabled_adapter_count || 0}/${data.adapters?.length || 0}`} detail={`Requires ${data.readiness?.required_adapter_maturity || 'certified_autonomous'}`} icon={ShieldCheck} />
            <Metric label="Queue" value={data.queue?.count || 0} detail={`${rejectableCount} removable before submit`} icon={Activity} />
            <Metric label="Open blockers" value={data.blockers?.count || 0} detail={`${data.handoffs?.count || 0} active handoffs`} icon={AlertTriangle} />
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel title="Active adapters" icon={ShieldCheck} count={`${data.adapters?.length || 0} enabled`} action={<Link className="text-xs font-semibold text-tomato-600" to="/adapter-health">Health</Link>}>
              <div className="space-y-2">
                {(data.adapters || []).map((adapter) => (
                  <div key={adapter.platform} className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 p-3">
                    <div>
                      <p className="text-sm font-semibold capitalize text-gray-900">{adapter.platform}</p>
                      <p className="text-[11px] text-gray-500">{adapter.unattended_eligible ? 'Eligible for unattended policy evaluation' : 'Not autonomous-eligible'}</p>
                    </div>
                    <Pill value={adapter.maturity}>{adapter.maturity}</Pill>
                  </div>
                ))}
                {!data.adapters?.length && <Empty>No platforms are opted into autonomous candidate processing.</Empty>}
              </div>
            </Panel>

            <Panel title="Caps & quiet hours" icon={Clock3} action={<Link className="text-xs font-semibold text-tomato-600" to="/scheduler">Policy</Link>}>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Metric label="Daily" value={`${data.caps?.remaining_daily ?? 0}/${data.caps?.daily_limit ?? 0}`} detail="remaining / cap" icon={CircleGauge} />
                <Metric label="Weekly" value={`${data.caps?.remaining_weekly ?? 0}/${data.caps?.weekly_limit ?? 0}`} detail="remaining / cap" icon={CircleGauge} />
                <Metric label="Per employer" value={data.caps?.per_employer_daily_limit ?? 0} detail="daily cap" icon={UsersRound} />
              </div>
              <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
                Quiet hours UTC: <strong>{data.caps?.quiet_hours_start_utc ?? '–'}:00 to {data.caps?.quiet_hours_end_utc ?? '–'}:00</strong>
              </div>
            </Panel>
          </div>

          <Panel title="Queue" icon={Activity} count={`${data.queue?.count || 0} active`} action={<Link className="text-xs font-semibold text-tomato-600" to="/queue">Full queue</Link>}>
            <div className="space-y-2">
              {queueItems.map((item) => (
                <div key={item.application_id} className="rounded-xl border border-gray-200 bg-white p-3">
                  <div className="flex items-start justify-between gap-3">
                    <Link to={item.application_path} className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-gray-900">{item.title}</p>
                      <p className="truncate text-xs text-gray-500">{item.company || 'Unknown employer'}</p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Pill value={item.automation_state}>{String(item.automation_state).replaceAll('_', ' ')}</Pill>
                        <Pill value={item.status}>{item.status}</Pill>
                        <span className="text-[11px] text-gray-400">Attempts {item.submission_attempt_count}</span>
                      </div>
                    </Link>
                    <button
                      type="button"
                      className="rounded-xl border border-red-200 px-3 py-2 text-xs font-semibold text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                      disabled={!online || mutationPending || !item.can_reject}
                      onClick={() => rejectMutation.mutate({ applicationId: item.application_id, title: item.title })}
                      aria-label={`Reject ${item.title} from autonomy queue`}
                      title={item.reject_blocker || 'Withdraw this pre-submission application from autonomy processing'}
                    >
                      <Ban className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" /> Reject
                    </button>
                  </div>
                  {!item.can_reject && item.reject_blocker && <p className="mt-2 text-[11px] text-gray-500">Reject unavailable: {String(item.reject_blocker).replaceAll('_', ' ')}</p>}
                </div>
              ))}
              {!queueItems.length && <Empty>No active application work is in the autonomy queue.</Empty>}
            </div>
          </Panel>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel title="Blockers" icon={ShieldAlert} count={`${data.blockers?.count || 0} need attention`} action={<Link className="text-xs font-semibold text-tomato-600" to="/recovery">Recovery</Link>}>
              <div className="space-y-2">
                {(data.blockers?.items || []).map((item, index) => (
                  <Link key={`${item.kind}-${item.review_id || item.task_id || index}`} to={item.action_path || '/recovery'} className="flex items-start justify-between gap-3 rounded-xl border border-gray-200 p-3 transition hover:border-tomato-300">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-gray-900">{item.title}</p>
                      <p className="mt-0.5 line-clamp-2 text-xs text-gray-500">{item.summary}</p>
                      <div className="mt-2"><Pill value={item.status}>{String(item.reason_code || item.status || item.kind).replaceAll('_', ' ')}</Pill></div>
                    </div>
                    <ChevronRight className="h-4 w-4 flex-shrink-0 text-gray-400" aria-hidden="true" />
                  </Link>
                ))}
                {!data.blockers?.items?.length && <Empty>No open review or dead-letter blockers.</Empty>}
              </div>
            </Panel>

            <Panel title="Handoffs" icon={Unplug} count={`${data.handoffs?.count || 0} active`} action={<Link className="text-xs font-semibold text-tomato-600" to="/handoff-review">Review</Link>}>
              <div className="space-y-2">
                {(data.handoffs?.items || []).map((item) => (
                  <Link key={item.handoff_id} to={item.action_path || '/handoff-review'} className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 p-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-gray-900">{item.title}</p>
                      <p className="truncate text-xs text-gray-500">{item.company || 'Unknown employer'} · {String(item.challenge_type).replaceAll('_', ' ')}</p>
                    </div>
                    <Pill value={item.status}>{String(item.status).replaceAll('_', ' ')}</Pill>
                  </Link>
                ))}
                {!data.handoffs?.items?.length && <Empty>No active human handoffs.</Empty>}
              </div>
            </Panel>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel title="Evidence" icon={BookOpenCheck} action={<Link className="text-xs font-semibold text-tomato-600" to={data.evidence?.evidence_path || '/evidence-materials'}>Open evidence</Link>}>
              <div className="grid grid-cols-2 gap-3">
                <Metric label="Verified materials" value={data.evidence?.verified_material_count || 0} detail={`${data.evidence?.material_review_required_count || 0} require review`} icon={BookOpenCheck} />
                <Metric label="Sufficient submit evidence" value={data.evidence?.sufficient_submission_evidence_count || 0} detail={`${data.evidence?.submission_evidence_count || 0} total records`} icon={Database} />
              </div>
            </Panel>

            <Panel title="Kill switches" icon={ShieldAlert}>
              <div className="space-y-2 text-xs">
                {[
                  ['Operator mode', data.kill_switches?.operator_mode],
                  ['Global kill switch', data.kill_switches?.global_kill_switch ? 'active' : 'off'],
                  ['Global autopilot', data.kill_switches?.global_autopilot_enabled ? 'enabled' : 'disabled'],
                  ['Real submit environment', data.kill_switches?.real_submission_enabled ? 'enabled' : 'off'],
                  ['Dry-run mode', data.kill_switches?.dry_run_mode ? 'on' : 'off'],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 px-3 py-2.5">
                    <span className="font-semibold text-gray-700">{label}</span>
                    <Pill value={value}>{String(value)}</Pill>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4 text-xs text-gray-600">
            <div className="flex items-start gap-2">
              <Square className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
              <p><strong>Reject means withdraw from JobTomatik autonomy.</strong> It does not claim the employer rejected you. Applications with any submission attempt, an in-flight attempt, or uncertain/submitted evidence cannot be rejected here and require dedicated review.</p>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
