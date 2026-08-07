import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircuitBoard,
  Clock3,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Square,
  Workflow,
  XCircle,
} from 'lucide-react'

import { getApiErrorMessage } from '../api/client'
import {
  approveAgentRun,
  cancelAgentRun,
  dispatchAgentRun,
  getAgentExecution,
  listAgentRuns,
  listSelectorDiagnostics,
  pauseAgentRun,
  resumeAgentRun,
  updateSelectorControl,
} from '../api/intelligence'

const ACTIVE_STATES = new Set(['planned', 'running', 'blocked'])
const TERMINAL_STATES = new Set(['completed', 'failed', 'cancelled'])

function statusClass(status) {
  if (status === 'completed') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'failed' || status === 'cancelled') return 'border-red-200 bg-red-50 text-red-700'
  if (status === 'blocked') return 'border-amber-200 bg-amber-50 text-amber-800'
  if (status === 'running' || status === 'queued') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'skipped') return 'border-slate-200 bg-slate-100 text-slate-600'
  return 'border-gray-200 bg-gray-50 text-gray-600'
}

function circuitClass(state) {
  if (state === 'healthy') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (state === 'degraded') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-red-200 bg-red-50 text-red-700'
}

function formatDate(value) {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

function compactOutput(output) {
  if (!output || Object.keys(output).length === 0) return 'No output yet.'
  const hidden = new Set(['execution'])
  const entries = Object.entries(output).filter(([key]) => !hidden.has(key))
  if (!entries.length) return 'Execution metadata recorded.'
  return entries
    .slice(0, 5)
    .map(([key, value]) => `${key.replaceAll('_', ' ')}: ${typeof value === 'object' ? JSON.stringify(value) : value}`)
    .join('\n')
}

function RunList({ runs, selectedRunId, onSelect, loading }) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 p-5 text-sm text-gray-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading runs…
      </div>
    )
  }
  if (!runs.length) {
    return (
      <div className="p-6 text-center text-sm text-gray-500">
        Create a plan in Command Center before bounded execution.
      </div>
    )
  }
  return (
    <div className="divide-y divide-gray-100">
      {runs.map((run) => (
        <button
          key={run.id}
          type="button"
          onClick={() => onSelect(run.id)}
          className={`w-full p-4 text-left transition ${selectedRunId === run.id ? 'bg-blue-50/70' : 'hover:bg-gray-50'}`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-bold text-gray-900">Run #{run.id}</div>
              <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500">
                {run.objective}
              </div>
            </div>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass(run.status)}`}>
              {run.status}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-gray-500">
            <span>{run.tasks.length} tasks</span>
            <span>•</span>
            <span>{run.risk_level} risk</span>
            <span>•</span>
            <span>{formatDate(run.created_at)}</span>
          </div>
        </button>
      ))}
    </div>
  )
}

function TaskTimeline({ tasks = [] }) {
  if (!tasks.length) {
    return <div className="text-sm text-gray-500">No tasks are attached to this run.</div>
  }
  return (
    <div className="space-y-3">
      {tasks.map((task, index) => (
        <div key={task.id} className="relative rounded-xl border border-gray-200 bg-white p-4">
          {index < tasks.length - 1 && (
            <span className="absolute left-[27px] top-12 h-[calc(100%+12px)] w-px bg-gray-200" aria-hidden="true" />
          )}
          <div className="flex items-start gap-3">
            <div className="relative z-10 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border border-gray-200 bg-white text-xs font-bold text-gray-500">
              {task.sequence + 1}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-gray-900">{task.name}</div>
                  <div className="mt-0.5 text-[11px] uppercase tracking-wide text-gray-400">
                    {task.agent_type.replaceAll('_', ' ')} · {task.plan_task_id}
                  </div>
                </div>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass(task.status)}`}>
                  {task.status}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-gray-500">
                <span>Attempts {task.attempt_count}/{task.max_attempts}</span>
                {task.dependencies?.length > 0 && <span>Depends on {task.dependencies.join(', ')}</span>}
              </div>
              {task.error && (
                <div className="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {task.error}
                </div>
              )}
              {task.task_output && Object.keys(task.task_output).length > 0 && (
                <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 px-3 py-2 text-[11px] leading-relaxed text-slate-200">
                  {compactOutput(task.task_output)}
                </pre>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function SelectorCircuits({ selectors, loading, onToggle, pendingId }) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div className="flex items-start justify-between gap-3 border-b border-gray-100 p-5">
        <div className="flex items-start gap-3">
          <div className="brand-icon-well h-10 w-10 flex-shrink-0">
            <CircuitBoard className="h-5 w-5" />
          </div>
          <div>
            <h2 className="font-bold text-gray-900">Selector circuits</h2>
            <p className="mt-1 text-xs leading-relaxed text-gray-500">
              Learned selectors remain account-scoped and can be opened manually when evidence degrades.
            </p>
          </div>
        </div>
      </div>
      <div className="divide-y divide-gray-100">
        {loading && (
          <div className="flex items-center gap-2 p-5 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading selector evidence…
          </div>
        )}
        {!loading && selectors.map((selector) => (
          <div key={selector.id} className="p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">{selector.platform}</span>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${circuitClass(selector.circuit_state)}`}>
                    {selector.circuit_state}
                  </span>
                  <span className="text-xs font-semibold text-gray-500">
                    {Math.round(selector.health_score * 100)}% health
                  </span>
                </div>
                <div className="mt-1 text-xs text-gray-500">
                  {selector.intent} · {selector.page_signature}
                </div>
                <code className="mt-2 block break-all rounded bg-gray-50 px-2 py-1.5 text-[11px] text-gray-600">
                  {selector.selector}
                </code>
                {selector.last_failure_reason && (
                  <div className="mt-2 text-xs text-red-600">Last failure: {selector.last_failure_reason}</div>
                )}
              </div>
              <button
                type="button"
                onClick={() => onToggle(selector)}
                disabled={pendingId === selector.id}
                className="btn-secondary inline-flex items-center justify-center gap-2 whitespace-nowrap"
              >
                {pendingId === selector.id
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : selector.is_disabled
                    ? <RotateCcw className="h-4 w-4" />
                    : <Ban className="h-4 w-4" />}
                {selector.is_disabled ? 'Close circuit' : 'Open circuit'}
              </button>
            </div>
          </div>
        ))}
        {!loading && selectors.length === 0 && (
          <div className="p-6 text-center text-sm text-gray-500">
            No selector outcomes have been recorded yet.
          </div>
        )}
      </div>
    </section>
  )
}

export default function ExecutionCenter() {
  const queryClient = useQueryClient()
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [acknowledgment, setAcknowledgment] = useState('')
  const [controlReason, setControlReason] = useState('Paused for operator review')

  const runsQuery = useQuery({
    queryKey: ['agent-runs', 'execution-center'],
    queryFn: () => listAgentRuns({ limit: 50 }),
    select: (response) => response.data || [],
    refetchInterval: 10_000,
  })
  const runs = runsQuery.data || []

  useEffect(() => {
    if (!selectedRunId && runs.length) setSelectedRunId(runs[0].id)
    if (selectedRunId && runs.length && !runs.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(runs[0].id)
    }
  }, [runs, selectedRunId])

  const executionQuery = useQuery({
    queryKey: ['agent-execution', selectedRunId],
    queryFn: () => getAgentExecution(selectedRunId),
    select: (response) => response.data,
    enabled: Boolean(selectedRunId),
    refetchInterval: (query) => {
      const snapshot = query.state.data
      return snapshot && ACTIVE_STATES.has(snapshot.status) ? 2500 : false
    },
  })
  const execution = executionQuery.data

  useEffect(() => {
    setAcknowledgment('')
  }, [selectedRunId])

  const selectorsQuery = useQuery({
    queryKey: ['selector-diagnostics'],
    queryFn: () => listSelectorDiagnostics({ include_disabled: true }),
    select: (response) => response.data || [],
    refetchInterval: 30_000,
  })

  const invalidateExecution = () => {
    queryClient.invalidateQueries({ queryKey: ['agent-execution', selectedRunId] })
    queryClient.invalidateQueries({ queryKey: ['agent-runs', 'execution-center'] })
    queryClient.invalidateQueries({ queryKey: ['intelligenceOverview'] })
  }

  const approveMutation = useMutation({
    mutationFn: () => approveAgentRun(selectedRunId, {
      acknowledgment,
      note: 'Approved from Execution Center for bounded local execution only.',
    }),
    onSuccess: () => {
      toast.success('Bounded execution approved. Submission and outreach remain unauthorized.')
      invalidateExecution()
      setAcknowledgment('')
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Approval failed')),
  })

  const dispatchMutation = useMutation({
    mutationFn: () => dispatchAgentRun(selectedRunId),
    onSuccess: () => {
      toast.success('Ready tasks queued.')
      invalidateExecution()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Dispatch failed')),
  })

  const pauseMutation = useMutation({
    mutationFn: () => pauseAgentRun(selectedRunId, { reason: controlReason }),
    onSuccess: () => {
      toast.success('Run paused.')
      invalidateExecution()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Pause failed')),
  })

  const resumeMutation = useMutation({
    mutationFn: () => resumeAgentRun(selectedRunId),
    onSuccess: () => {
      toast.success('Run resumed and ready tasks queued.')
      invalidateExecution()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Resume failed')),
  })

  const cancelMutation = useMutation({
    mutationFn: () => cancelAgentRun(selectedRunId, { reason: controlReason || 'Cancelled by operator' }),
    onSuccess: () => {
      toast.success('Run cancelled. Pending work was skipped.')
      invalidateExecution()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Cancellation failed')),
  })

  const selectorMutation = useMutation({
    mutationFn: (selector) => updateSelectorControl(selector.id, {
      is_disabled: !selector.is_disabled,
      reason: selector.is_disabled
        ? 'Operator restored selector after review'
        : 'Operator opened circuit from diagnostics',
    }),
    onSuccess: () => {
      toast.success('Selector circuit updated.')
      queryClient.invalidateQueries({ queryKey: ['selector-diagnostics'] })
      queryClient.invalidateQueries({ queryKey: ['intelligenceOverview'] })
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Selector update failed')),
  })

  const expectedAcknowledgment = selectedRunId ? `APPROVE BOUNDED RUN ${selectedRunId}` : ''
  const approvalReady = acknowledgment === expectedAcknowledgment
  const canDispatch = Boolean(
    execution
      && !execution.paused
      && !execution.cancellation_requested
      && !TERMINAL_STATES.has(execution.status)
      && ['approved', 'not_required'].includes(execution.approval_state),
  )
  const controlBusy = approveMutation.isPending
    || dispatchMutation.isPending
    || pauseMutation.isPending
    || resumeMutation.isPending
    || cancelMutation.isPending

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-tomato-600">
          <Workflow className="h-4 w-4" />
          Bounded orchestration
        </div>
        <h1 className="mt-2 text-xl font-bold text-gray-900 md:text-2xl">Execution Center</h1>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-gray-500">
          Approve and observe dependency-aware agent tasks. This layer prepares evidence, analysis,
          materials, and readiness only. It cannot submit applications or send recruiter messages.
        </p>
      </div>

      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-700" />
          <div>
            <div className="font-semibold text-emerald-950">Hard execution boundary</div>
            <div className="mt-1 text-xs leading-relaxed text-emerald-800">
              Bounded approval authorizes local preparation only. Submission, outreach, offer acceptance,
              negotiation sending, CAPTCHA handling, login, and MFA remain outside this control plane.
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <div>
              <h2 className="font-bold text-gray-900">Agent runs</h2>
              <p className="text-xs text-gray-500">Newest first</p>
            </div>
            <button
              type="button"
              onClick={() => runsQuery.refetch()}
              className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"
              aria-label="Refresh agent runs"
            >
              <RefreshCw className={`h-4 w-4 ${runsQuery.isFetching ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <RunList
            runs={runs}
            selectedRunId={selectedRunId}
            onSelect={setSelectedRunId}
            loading={runsQuery.isLoading}
          />
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          {!selectedRunId ? (
            <div className="py-16 text-center text-sm text-gray-500">Select an agent run.</div>
          ) : executionQuery.isLoading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-gray-500">
              <Loader2 className="h-5 w-5 animate-spin" /> Loading execution state…
            </div>
          ) : execution ? (
            <div className="space-y-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-lg font-bold text-gray-900">Run #{execution.run_id}</h2>
                    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass(execution.status)}`}>
                      {execution.status}
                    </span>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                      {execution.risk_level} risk
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-gray-600">{execution.objective}</p>
                </div>
                <div className="text-right text-xs text-gray-500">
                  <div>{execution.execution_scope.replaceAll('_', ' ')}</div>
                  <div className="mt-1 font-semibold">
                    Approval: {execution.approval_state.replaceAll('_', ' ')}
                  </div>
                </div>
              </div>

              {execution.requires_approval && execution.approval_state === 'pending' && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-700" />
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-amber-950">Explicit approval required</div>
                      <p className="mt-1 text-xs leading-relaxed text-amber-800">
                        Type the exact phrase below. This does not authorize submission or outreach.
                      </p>
                      <code className="mt-3 block break-all rounded bg-white px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">
                        {expectedAcknowledgment}
                      </code>
                      <input
                        value={acknowledgment}
                        onChange={(event) => setAcknowledgment(event.target.value)}
                        className="input mt-3 font-mono"
                        placeholder="Type the exact phrase"
                        autoComplete="off"
                      />
                      <button
                        type="button"
                        onClick={() => approveMutation.mutate()}
                        disabled={!approvalReady || approveMutation.isPending}
                        className="btn-primary mt-3 inline-flex items-center gap-2 disabled:opacity-50"
                      >
                        {approveMutation.isPending
                          ? <Loader2 className="h-4 w-4 animate-spin" />
                          : <ShieldCheck className="h-4 w-4" />}
                        Approve bounded run
                      </button>
                    </div>
                  </div>
                </div>
              )}

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                <label className="label">Operator control reason</label>
                <input
                  value={controlReason}
                  onChange={(event) => setControlReason(event.target.value)}
                  className="input"
                  placeholder="Reason for pause or cancellation"
                />
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => dispatchMutation.mutate()}
                    disabled={!canDispatch || controlBusy}
                    className="btn-primary inline-flex items-center gap-2 disabled:opacity-50"
                  >
                    {dispatchMutation.isPending
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <Play className="h-4 w-4" />}
                    Dispatch ready tasks
                  </button>
                  {!execution.paused && !TERMINAL_STATES.has(execution.status) && (
                    <button
                      type="button"
                      onClick={() => pauseMutation.mutate()}
                      disabled={controlBusy || controlReason.trim().length < 3}
                      className="btn-secondary inline-flex items-center gap-2"
                    >
                      <Pause className="h-4 w-4" /> Pause
                    </button>
                  )}
                  {execution.paused && !execution.cancellation_requested && !TERMINAL_STATES.has(execution.status) && (
                    <button
                      type="button"
                      onClick={() => resumeMutation.mutate()}
                      disabled={controlBusy}
                      className="btn-secondary inline-flex items-center gap-2"
                    >
                      <RotateCcw className="h-4 w-4" /> Resume
                    </button>
                  )}
                  {!TERMINAL_STATES.has(execution.status) && (
                    <button
                      type="button"
                      onClick={() => cancelMutation.mutate()}
                      disabled={controlBusy || controlReason.trim().length < 3}
                      className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      <Square className="h-4 w-4" /> Cancel run
                    </button>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {Object.entries(execution.task_counts || {}).map(([status, count]) => (
                  <div key={status} className="rounded-xl border border-gray-200 bg-white p-3 text-center">
                    <div className="text-xl font-bold text-gray-900">{count}</div>
                    <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                      {status}
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="font-bold text-gray-900">Task timeline</h3>
                    <p className="text-xs text-gray-500">
                      Dependencies release work in waves. Blocked tasks halt their downstream chain.
                    </p>
                  </div>
                  {executionQuery.isFetching && <Loader2 className="h-4 w-4 animate-spin text-gray-400" />}
                </div>
                <TaskTimeline tasks={execution.tasks} />
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2 py-16 text-sm text-red-600">
              <XCircle className="h-5 w-5" /> Execution state could not be loaded.
            </div>
          )}
        </section>
      </div>

      <SelectorCircuits
        selectors={selectorsQuery.data || []}
        loading={selectorsQuery.isLoading}
        onToggle={(selector) => selectorMutation.mutate(selector)}
        pendingId={selectorMutation.variables?.id}
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm">
          <CheckCircle2 className="h-5 w-5 text-emerald-600" />
          <div className="mt-2 font-semibold text-gray-900">Inspectable outputs</div>
          <div className="mt-1 text-xs text-gray-500">Each task stores attempts, dependencies, output, errors, and execution metadata.</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm">
          <Clock3 className="h-5 w-5 text-blue-600" />
          <div className="mt-2 font-semibold text-gray-900">Bounded retries</div>
          <div className="mt-1 text-xs text-gray-500">Claims use leases and hard attempt caps, preventing duplicate concurrent execution.</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm">
          <Ban className="h-5 w-5 text-red-600" />
          <div className="mt-2 font-semibold text-gray-900">No consequential action</div>
          <div className="mt-1 text-xs text-gray-500">Application and recruiter tasks stop at readiness and relationship intelligence.</div>
        </div>
      </div>
    </div>
  )
}
