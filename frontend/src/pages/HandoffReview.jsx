import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  Fingerprint,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'

import { getApiErrorMessage } from '../api/client'
import {
  createSubmissionHandoff,
  getSubmissionHandoff,
  listAgentRuns,
  reviewSubmissionHandoff,
} from '../api/intelligence'

function formatDate(value) {
  if (!value) return 'Not recorded'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(parsed)
}

function statusClass(status) {
  if (status === 'reviewed') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'created') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'drifted') return 'border-red-200 bg-red-50 text-red-700'
  return 'border-gray-200 bg-gray-50 text-gray-600'
}

function HashRow({ label, value }) {
  return (
    <div className="grid gap-1 border-b border-gray-100 py-3 last:border-0 sm:grid-cols-[190px_minmax(0,1fr)]">
      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div>
      <code className="break-all text-xs text-gray-700">{value || 'Not available'}</code>
    </div>
  )
}

function RunPicker({ runs, selected, onSelect, loading }) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-100 p-4">
        <h2 className="font-bold text-gray-900">Completed bounded runs</h2>
        <p className="mt-1 text-xs text-gray-500">Only completed runs can produce a handoff dossier.</p>
      </div>
      {loading && (
        <div className="flex items-center gap-2 p-5 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading runs…
        </div>
      )}
      {!loading && runs.length === 0 && (
        <div className="p-6 text-sm text-gray-500">
          No completed bounded runs are available yet.
        </div>
      )}
      <div className="divide-y divide-gray-100">
        {runs.map((run) => (
          <button
            key={run.id}
            type="button"
            onClick={() => onSelect(run.id)}
            className={`w-full p-4 text-left transition ${selected === run.id ? 'bg-blue-50/70' : 'hover:bg-gray-50'}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-bold text-gray-900">Run #{run.id}</div>
                <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500">
                  {run.objective}
                </div>
              </div>
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                completed
              </span>
            </div>
            <div className="mt-2 text-[11px] text-gray-400">{formatDate(run.created_at)}</div>
          </button>
        ))}
      </div>
    </section>
  )
}

export default function HandoffReview() {
  const queryClient = useQueryClient()
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [createAck, setCreateAck] = useState('')
  const [reviewAck, setReviewAck] = useState('')
  const [reviewNote, setReviewNote] = useState('Reviewed locally. Final-submit approval remains separate.')

  const runsQuery = useQuery({
    queryKey: ['agent-runs', 'handoff-review'],
    queryFn: () => listAgentRuns({ limit: 100 }),
    select: (response) => (response.data || []).filter((run) => run.status === 'completed'),
    refetchInterval: 15_000,
  })
  const runs = runsQuery.data || []

  useEffect(() => {
    if (!selectedRunId && runs.length) setSelectedRunId(runs[0].id)
    if (selectedRunId && runs.length && !runs.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(runs[0].id)
    }
  }, [runs, selectedRunId])

  useEffect(() => {
    setCreateAck('')
    setReviewAck('')
  }, [selectedRunId])

  const handoffQuery = useQuery({
    queryKey: ['submission-handoff', selectedRunId],
    queryFn: () => getSubmissionHandoff(selectedRunId),
    select: (response) => response.data,
    enabled: Boolean(selectedRunId),
    refetchInterval: 5000,
  })
  const handoff = handoffQuery.data

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['submission-handoff', selectedRunId] })
    queryClient.invalidateQueries({ queryKey: ['agent-runs', 'handoff-review'] })
  }

  const createMutation = useMutation({
    mutationFn: () => createSubmissionHandoff(selectedRunId, { acknowledgment: createAck }),
    onSuccess: () => {
      toast.success('Hash-only submission handoff created. No approval was issued.')
      setCreateAck('')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Handoff creation failed')),
  })

  const reviewMutation = useMutation({
    mutationFn: () => reviewSubmissionHandoff(selectedRunId, {
      acknowledgment: reviewAck,
      note: reviewNote,
    }),
    onSuccess: () => {
      toast.success('Handoff reviewed. Final-submit consent is still required separately.')
      setReviewAck('')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Handoff review failed')),
  })

  const snapshot = handoff?.current_snapshot || handoff?.stored_snapshot
  const stored = handoff?.stored_snapshot
  const preflight = snapshot?.supervised_preflight
  const createReady = Boolean(handoff?.eligible && createAck === handoff.expected_create_acknowledgment)
  const reviewReady = Boolean(
    handoff?.exists
      && !handoff?.drifted
      && handoff?.eligible
      && handoff?.status !== 'reviewed'
      && reviewAck === handoff.expected_review_acknowledgment,
  )
  const blockers = useMemo(() => handoff?.blockers || [], [handoff])

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-tomato-600">
          <Fingerprint className="h-4 w-4" />
          Phase 5 review boundary
        </div>
        <h1 className="mt-2 text-xl font-bold text-gray-900 md:text-2xl">Submission Handoff Review</h1>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-gray-500">
          Bind a completed bounded run to the exact current payload, detect drift, and review the dossier before opening the separate supervised-submission workflow.
        </p>
      </div>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-700" />
          <div>
            <div className="font-bold text-amber-900">Review is not final-submit approval</div>
            <p className="mt-1 text-sm leading-relaxed text-amber-800">
              This workspace cannot issue a submission approval, reserve an attempt, publish a worker task, open a browser, or send outreach. Those flags remain false even after review.
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[330px_minmax(0,1fr)]">
        <RunPicker
          runs={runs}
          selected={selectedRunId}
          onSelect={setSelectedRunId}
          loading={runsQuery.isLoading}
        />

        <div className="space-y-5">
          {!selectedRunId && (
            <section className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-500 shadow-sm">
              Select a completed run to inspect its handoff eligibility.
            </section>
          )}

          {selectedRunId && handoffQuery.isLoading && (
            <section className="flex items-center gap-2 rounded-2xl border border-gray-200 bg-white p-6 text-sm text-gray-500 shadow-sm">
              <Loader2 className="h-4 w-4 animate-spin" /> Building current hash snapshot…
            </section>
          )}

          {handoff && (
            <>
              <section className="rounded-2xl border border-gray-200 bg-white shadow-sm">
                <div className="flex flex-col gap-3 border-b border-gray-100 p-5 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-bold text-gray-900">Run #{handoff.run_id} dossier</h2>
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass(handoff.status)}`}>
                        {handoff.status.replaceAll('_', ' ')}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      Application {handoff.application_id || 'not resolved'} · hash-only retained record
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handoffQuery.refetch()}
                    disabled={handoffQuery.isFetching}
                    className="btn-secondary inline-flex items-center justify-center gap-2"
                  >
                    {handoffQuery.isFetching
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <RefreshCw className="h-4 w-4" />}
                    Recheck drift
                  </button>
                </div>

                <div className="grid gap-3 p-5 sm:grid-cols-3">
                  {[
                    ['Submission authorized', handoff.submission_authorized],
                    ['Approval issued', handoff.approval_issued],
                    ['Queue attempted', handoff.queue_attempted],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl border border-emerald-100 bg-emerald-50 p-3">
                      <div className="flex items-center gap-2 text-sm font-bold text-emerald-800">
                        <ShieldCheck className="h-4 w-4" /> {value ? 'Unexpected true' : 'False'}
                      </div>
                      <div className="mt-1 text-xs text-emerald-700">{label}</div>
                    </div>
                  ))}
                </div>

                {handoff.drifted && (
                  <div className="mx-5 mb-5 rounded-xl border border-red-200 bg-red-50 p-4">
                    <div className="flex items-center gap-2 font-bold text-red-800">
                      <AlertTriangle className="h-4 w-4" /> Dossier drift detected
                    </div>
                    <ul className="mt-2 space-y-1 text-xs text-red-700">
                      {handoff.drift_reasons.map((reason) => <li key={reason}>• {reason}</li>)}
                    </ul>
                    <p className="mt-2 text-xs text-red-700">Regenerate the handoff before review.</p>
                  </div>
                )}

                {!handoff.eligible && blockers.length > 0 && (
                  <div className="mx-5 mb-5 rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <div className="font-bold text-amber-900">Handoff creation is blocked</div>
                    <ul className="mt-2 space-y-1 text-xs text-amber-800">
                      {blockers.map((blocker) => <li key={blocker}>• {blocker.replaceAll('_', ' ')}</li>)}
                    </ul>
                  </div>
                )}
              </section>

              {snapshot && (
                <section className="rounded-2xl border border-gray-200 bg-white shadow-sm">
                  <div className="border-b border-gray-100 p-5">
                    <div className="flex items-start gap-3">
                      <div className="brand-icon-well h-10 w-10 flex-shrink-0">
                        <FileCheck2 className="h-5 w-5" />
                      </div>
                      <div>
                        <h2 className="font-bold text-gray-900">Exact retained snapshot</h2>
                        <p className="mt-1 text-xs text-gray-500">Hashes only. Applicant contents are not copied into the dossier.</p>
                      </div>
                    </div>
                  </div>
                  <div className="px-5">
                    <HashRow label="Handoff hash" value={snapshot.handoff_hash} />
                    <HashRow label="Combined payload" value={snapshot.combined_payload_hash} />
                    <HashRow label="Task ledger" value={snapshot.task_ledger_hash} />
                    <HashRow label="Profile snapshot" value={snapshot.profile_snapshot_hash} />
                    <HashRow label="Résumé" value={snapshot.resume_hash} />
                    <HashRow label="Cover letter" value={snapshot.cover_letter_hash} />
                    <HashRow label="Answer policies" value={snapshot.answer_payload_hash} />
                    <HashRow label="Target identity" value={snapshot.target_identity_hash} />
                  </div>
                </section>
              )}

              <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                <h2 className="font-bold text-gray-900">Separate supervised preflight</h2>
                <p className="mt-1 text-xs leading-relaxed text-gray-500">
                  The current supervised engine independently evaluates feature flags, platform pilot status, application state, exact target identity, manual reviews, and payload hashes.
                </p>
                {preflight && (
                  <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="flex items-center gap-2">
                      {preflight.ready
                        ? <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                        : <AlertTriangle className="h-5 w-5 text-amber-600" />}
                      <div className="font-bold text-gray-900">
                        {preflight.ready ? 'Current supervised preflight is ready' : 'Current supervised preflight remains blocked'}
                      </div>
                    </div>
                    {!preflight.ready && (
                      <ul className="mt-3 space-y-1 text-xs text-gray-600">
                        {(preflight.blockers || []).map((blocker) => <li key={blocker}>• {blocker.replaceAll('_', ' ')}</li>)}
                      </ul>
                    )}
                  </div>
                )}
              </section>

              <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                <h2 className="font-bold text-gray-900">Create or refresh dossier</h2>
                <p className="mt-1 text-xs text-gray-500">
                  Type the exact phrase. Refreshing replaces the stored hash snapshot and clears the prior review.
                </p>
                <code className="mt-3 block rounded-lg bg-slate-950 px-3 py-2 text-xs text-slate-100">
                  {handoff.expected_create_acknowledgment}
                </code>
                <input
                  value={createAck}
                  onChange={(event) => setCreateAck(event.target.value)}
                  className="input mt-3 w-full"
                  placeholder="Exact creation acknowledgment"
                />
                <button
                  type="button"
                  onClick={() => createMutation.mutate()}
                  disabled={!createReady || createMutation.isPending}
                  className="btn-primary mt-3 inline-flex items-center justify-center gap-2"
                >
                  {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Fingerprint className="h-4 w-4" />}
                  {handoff.exists ? 'Refresh handoff' : 'Create handoff'}
                </button>
              </section>

              {handoff.exists && !handoff.drifted && (
                <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                  <h2 className="font-bold text-gray-900">Record local review</h2>
                  <p className="mt-1 text-xs text-gray-500">
                    Reviewing confirms only that you inspected this exact dossier. It does not confirm final submit.
                  </p>
                  <code className="mt-3 block rounded-lg bg-slate-950 px-3 py-2 text-xs text-slate-100">
                    {handoff.expected_review_acknowledgment}
                  </code>
                  <input
                    value={reviewAck}
                    onChange={(event) => setReviewAck(event.target.value)}
                    className="input mt-3 w-full"
                    placeholder="Exact review acknowledgment"
                  />
                  <textarea
                    value={reviewNote}
                    onChange={(event) => setReviewNote(event.target.value)}
                    className="input mt-3 min-h-24 w-full"
                    maxLength={1000}
                  />
                  <button
                    type="button"
                    onClick={() => reviewMutation.mutate()}
                    disabled={!reviewReady || reviewMutation.isPending}
                    className="btn-primary mt-3 inline-flex items-center justify-center gap-2"
                  >
                    {reviewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                    Record review
                  </button>
                  {stored?.reviewed_at && (
                    <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                      Reviewed {formatDate(stored.reviewed_at)}. No submission approval was issued.
                    </div>
                  )}
                </section>
              )}

              {handoff.status === 'reviewed' && handoff.application_id && (
                <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="font-bold text-blue-900">Continue to the separate application workflow</div>
                      <p className="mt-1 text-sm text-blue-800">
                        Application Detail performs fresh supervised preflight and requires its own exact final-submit approval.
                      </p>
                    </div>
                    <Link
                      to={`/applications/${handoff.application_id}`}
                      className="btn-primary inline-flex items-center justify-center gap-2 whitespace-nowrap"
                    >
                      Open application <ArrowRight className="h-4 w-4" />
                    </Link>
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
