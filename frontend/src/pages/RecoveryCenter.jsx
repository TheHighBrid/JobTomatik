import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, RefreshCw, RotateCcw, ShieldAlert } from 'lucide-react'
import api, { getApiErrorMessage } from '../api/client'


function shortHash(value) {
  const text = String(value || '')
  if (text.length <= 20) return text || 'unavailable'
  return `${text.slice(0, 10)}…${text.slice(-8)}`
}

function DeadLetterCard({ item }) {
  const queryClient = useQueryClient()
  const [acknowledgment, setAcknowledgment] = useState('')
  const [note, setNote] = useState('Reviewed; no bounded retry is required.')
  const envelope = item.dead_letter || {}

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['deadLetters'] })
  const requeue = useMutation({
    mutationFn: () => api.post(`/recovery/dead-letters/${item.task_id}/requeue`, { acknowledgment }),
    onSuccess: refresh,
  })
  const resolve = useMutation({
    mutationFn: () => api.post(`/recovery/dead-letters/${item.task_id}/resolve`, { acknowledgment, note }),
    onSuccess: refresh,
  })
  const error = requeue.error || resolve.error

  return (
    <div className="card p-5 space-y-4">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-gray-900">Run #{item.run_id} · Task #{item.task_id}</span>
            <span className="badge border-red-300 bg-red-50 text-red-700">{envelope.status || 'open'}</span>
          </div>
          <div className="mt-1 text-sm text-gray-600">{item.task_name} · {item.agent_type}</div>
          <div className="mt-1 text-xs text-gray-500">{envelope.failure_class || 'unknown failure'} · attempt {item.attempt_count}/{item.max_attempts}</div>
        </div>
        <div className="text-xs text-gray-500 font-mono">{shortHash(envelope.checkpoint_hash)}</div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
        <div className="font-semibold text-gray-900">Retained checkpoint</div>
        <div className="mt-1">Plan task: {item.plan_task_id}</div>
        <div>Automatic retry: {envelope.automatic_retry_allowed ? 'enabled' : 'disabled'}</div>
        <div>Manual requeues: {envelope.requeue_count || 0}/{envelope.requeue_limit || 0}</div>
        {envelope.error && <div className="mt-2 whitespace-pre-wrap break-words">{envelope.error}</div>}
      </div>

      <div className="space-y-2">
        <div className="text-xs font-semibold text-gray-700">Exact recovery acknowledgment</div>
        <input
          value={acknowledgment}
          onChange={(event) => setAcknowledgment(event.target.value)}
          placeholder={envelope.expected_requeue_acknowledgment || 'Exact acknowledgment'}
          className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-mono"
        />
        <div className="grid md:grid-cols-2 gap-2 text-[11px] text-gray-500">
          <div className="rounded-lg bg-gray-50 p-2 break-all">Requeue: {envelope.expected_requeue_acknowledgment}</div>
          <div className="rounded-lg bg-gray-50 p-2 break-all">Resolve: {envelope.expected_resolve_acknowledgment}</div>
        </div>
      </div>

      <div className="grid md:grid-cols-[1fr_auto_auto] gap-2 items-end">
        <div>
          <label className="text-xs font-semibold text-gray-700" htmlFor={`resolution-${item.task_id}`}>Resolution note</label>
          <input
            id={`resolution-${item.task_id}`}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm"
          />
        </div>
        <button
          type="button"
          disabled={requeue.isPending || resolve.isPending}
          onClick={() => requeue.mutate()}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          <RotateCcw className="w-4 h-4" /> Requeue bounded task
        </button>
        <button
          type="button"
          disabled={requeue.isPending || resolve.isPending}
          onClick={() => resolve.mutate()}
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-semibold text-gray-800 disabled:opacity-50"
        >
          <CheckCircle2 className="w-4 h-4" /> Resolve without retry
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
          {getApiErrorMessage(error, 'Recovery action was blocked.')}
        </div>
      )}
      {requeue.data?.data?.dispatch_task_id && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
          Bounded dispatch queued: {requeue.data.data.dispatch_task_id}
        </div>
      )}
    </div>
  )
}

export default function RecoveryCenter() {
  const [status, setStatus] = useState('open')
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['deadLetters', status],
    queryFn: () => api.get('/recovery/dead-letters', { params: { status, limit: 200 } }),
    select: (response) => response.data,
    refetchInterval: 60_000,
  })
  const items = useMemo(() => data?.dead_letters || [], [data])

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl md:text-2xl font-bold text-gray-900">Recovery Center</h1>
            <span className="badge border-amber-300 bg-amber-50 text-amber-700">checkpoint-bound</span>
          </div>
          <p className="text-gray-500 mt-1 text-sm">Review irrecoverable bounded tasks without replaying unknown state.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm"
            aria-label="Dead-letter status"
          >
            <option value="open">Open</option>
            <option value="requeued">Requeued</option>
            <option value="resolved">Resolved</option>
            <option value="all">All</option>
          </select>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900 flex items-start gap-3">
        <ShieldAlert className="w-5 h-5 mt-0.5 flex-shrink-0" />
        <div>
          <div className="font-semibold">Recovery is not submission permission.</div>
          <div className="mt-1 text-xs">A requeue can run one bounded local task from the exact retained checkpoint. It cannot submit an application, send recruiter outreach, promote adapter maturity, reset a circuit breaker, or enable automatic retry.</div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          {getApiErrorMessage(error, 'Dead-letter queue could not be loaded.')}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">{[1, 2, 3].map((value) => <div key={value} className="h-48 rounded-2xl bg-gray-100 animate-pulse" />)}</div>
      ) : items.length === 0 ? (
        <div className="card p-10 text-center">
          <CheckCircle2 className="w-10 h-10 mx-auto text-emerald-500" />
          <div className="mt-3 font-semibold text-gray-900">No {status === 'all' ? '' : status} dead letters</div>
          <div className="mt-1 text-sm text-gray-500">Irrecoverable bounded work will appear here with a retained checkpoint.</div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <AlertTriangle className="w-4 h-4 text-amber-500" /> {items.length} retained recovery record{items.length === 1 ? '' : 's'}
          </div>
          {items.map((item) => <DeadLetterCard key={`${item.run_id}-${item.task_id}-${item.dead_letter?.status}`} item={item} />)}
        </div>
      )}
    </div>
  )
}
