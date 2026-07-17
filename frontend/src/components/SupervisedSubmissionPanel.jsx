import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Hash,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Send,
  ShieldCheck,
  Timer,
  XCircle,
} from 'lucide-react'
import {
  createSupervisedSubmissionApproval,
  getApiErrorMessage,
  getSupervisedSubmissionPreflight,
  listSupervisedSubmissionApprovals,
  queueSupervisedSubmission,
  revokeSupervisedSubmissionApproval,
} from '../api/client'


const BLOCKER_LABELS = {
  global_live_submit_disabled: 'The global real-submission switch is off.',
  greenhouse_supervised_pilot_disabled: 'The Greenhouse supervised-pilot switch is off.',
  unsupported_platform: 'This application is not a supported Greenhouse target.',
  application_not_ready_to_apply: 'The application is not in the ready-to-apply state.',
  unresolved_manual_reviews: 'Resolve every open manual-review task first.',
  missing_application_url: 'The exact application URL is missing.',
  missing_submission_idempotency_key: 'The duplicate-prevention key is missing.',
  resume_missing_or_unreadable: 'The selected résumé is missing or unreadable.',
}

const TERMINAL_STATUSES = new Set(['consumed', 'revoked', 'expired'])

function ShortHash({ label, value }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        <Hash className="h-3.5 w-3.5" />
        {label}
      </div>
      <code className="mt-1 block break-all text-[11px] leading-relaxed text-gray-700">
        {value || 'Unavailable'}
      </code>
    </div>
  )
}

function ApprovalStatus({ status }) {
  const styles = {
    active: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    consumed: 'border-blue-200 bg-blue-50 text-blue-700',
    revoked: 'border-red-200 bg-red-50 text-red-700',
    expired: 'border-gray-200 bg-gray-50 text-gray-600',
  }
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${styles[status] || styles.expired}`}>
      {status || 'unknown'}
    </span>
  )
}

export default function SupervisedSubmissionPanel({ application }) {
  const applicationId = application?.id
  const qc = useQueryClient()
  const [confirmEmployer, setConfirmEmployer] = useState('')
  const [confirmRole, setConfirmRole] = useState('')
  const [confirmUrl, setConfirmUrl] = useState('')
  const [confirmFinalSubmit, setConfirmFinalSubmit] = useState(false)
  const [reviewedHashes, setReviewedHashes] = useState(false)
  const [notes, setNotes] = useState('')

  const preflightQuery = useQuery({
    queryKey: ['supervised-preflight', applicationId],
    queryFn: () => getSupervisedSubmissionPreflight(applicationId),
    select: (response) => response.data,
    enabled: Boolean(applicationId),
    retry: false,
    refetchOnWindowFocus: true,
  })

  const preflight = preflightQuery.data
  const isGreenhouse = preflight?.platform === 'greenhouse'

  const approvalsQuery = useQuery({
    queryKey: ['supervised-approvals', applicationId],
    queryFn: () => listSupervisedSubmissionApprovals(applicationId),
    select: (response) => response.data,
    enabled: Boolean(applicationId && isGreenhouse),
    retry: false,
  })

  const approvals = approvalsQuery.data || []
  const activeApproval = useMemo(
    () => approvals.find((item) => item.status === 'active') || null,
    [approvals],
  )
  const latestApproval = activeApproval || approvals[0] || null

  useEffect(() => {
    setConfirmEmployer('')
    setConfirmRole('')
    setConfirmUrl('')
    setConfirmFinalSubmit(false)
    setReviewedHashes(false)
    setNotes('')
  }, [applicationId, preflight?.combined_payload_hash])

  const refreshAll = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['supervised-preflight', applicationId] }),
      qc.invalidateQueries({ queryKey: ['supervised-approvals', applicationId] }),
      qc.invalidateQueries({ queryKey: ['application', String(applicationId)] }),
      qc.invalidateQueries({ queryKey: ['application', applicationId] }),
    ])
  }

  const createApproval = useMutation({
    mutationFn: () => createSupervisedSubmissionApproval(applicationId, {
      confirm_employer: confirmEmployer,
      confirm_role: confirmRole,
      confirm_application_url: confirmUrl,
      confirm_final_submit: confirmFinalSubmit,
      expires_in_minutes: 20,
      notes: notes.trim() || null,
    }),
    onSuccess: async () => {
      toast.success('One-time supervised approval issued.')
      await refreshAll()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Approval could not be issued.')),
  })

  const revokeApproval = useMutation({
    mutationFn: (reference) => revokeSupervisedSubmissionApproval(
      applicationId,
      reference,
      { reason: 'revoked_by_user' },
    ),
    onSuccess: async () => {
      toast.success('Approval revoked.')
      await refreshAll()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Approval could not be revoked.')),
  })

  const queueSubmission = useMutation({
    mutationFn: (reference) => queueSupervisedSubmission(applicationId, reference),
    onSuccess: async (response) => {
      toast.success(`Supervised submission queued: ${response.data.task_id}`)
      setReviewedHashes(false)
      await refreshAll()
      setTimeout(refreshAll, 3000)
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Supervised submission was blocked.')),
  })

  if (preflightQuery.isLoading) {
    return (
      <div className="card p-5">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Checking supervised-submission boundary…
        </div>
      </div>
    )
  }

  if (preflightQuery.isError || !isGreenhouse) return null

  const exactConfirmationsMatch = (
    confirmEmployer === preflight.employer
    && confirmRole === preflight.role
    && confirmUrl === preflight.application_url
  )
  const canIssue = (
    preflight.ready
    && exactConfirmationsMatch
    && confirmFinalSubmit
    && !activeApproval
    && !createApproval.isPending
  )
  const approvalExpiredLocally = activeApproval
    ? new Date(activeApproval.expires_at).getTime() <= Date.now()
    : false
  const canQueue = Boolean(
    activeApproval
    && !approvalExpiredLocally
    && reviewedHashes
    && !queueSubmission.isPending
  )

  return (
    <section className="card overflow-hidden border border-slate-200">
      <div className="border-b border-slate-200 bg-slate-950 px-5 py-4 text-white">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <LockKeyhole className="h-5 w-5 text-emerald-300" />
              <h2 className="font-semibold">Greenhouse supervised submission</h2>
            </div>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-300">
              A live attempt requires two disabled-by-default feature flags and one short-lived approval bound to this exact payload.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${preflight.ready ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200' : 'border-amber-400/40 bg-amber-400/10 text-amber-100'}`}>
              {preflight.ready ? 'Preflight ready' : 'Preflight blocked'}
            </span>
            <button
              type="button"
              onClick={() => preflightQuery.refetch()}
              disabled={preflightQuery.isFetching}
              className="rounded-lg border border-white/20 p-2 text-slate-200 hover:bg-white/10 disabled:opacity-50"
              aria-label="Refresh supervised preflight"
            >
              <RefreshCw className={`h-4 w-4 ${preflightQuery.isFetching ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-5 p-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-gray-200 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Exact target</div>
            <div className="mt-1 text-sm font-semibold text-gray-900">{preflight.role}</div>
            <div className="text-sm text-gray-600">{preflight.employer}</div>
            <div className="mt-2 break-all text-xs text-gray-500">{preflight.application_url}</div>
          </div>
          <div className="rounded-xl border border-gray-200 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Safety state</div>
            <div className="mt-2 space-y-1.5 text-xs">
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-600">Global live switch</span>
                <span className={preflight.global_live_submit_enabled ? 'font-semibold text-emerald-700' : 'font-semibold text-gray-500'}>
                  {preflight.global_live_submit_enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-600">Greenhouse pilot switch</span>
                <span className={preflight.platform_pilot_enabled ? 'font-semibold text-emerald-700' : 'font-semibold text-gray-500'}>
                  {preflight.platform_pilot_enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-600">Open manual reviews</span>
                <span className={preflight.unresolved_manual_review_count ? 'font-semibold text-red-700' : 'font-semibold text-emerald-700'}>
                  {preflight.unresolved_manual_review_count}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-gray-600">State</span>
                <span className="font-semibold text-gray-800">{preflight.automation_state}</span>
              </div>
            </div>
          </div>
        </div>

        {!preflight.ready && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
              <AlertTriangle className="h-4 w-4" />
              Approval is unavailable
            </div>
            <ul className="mt-2 space-y-1 text-xs text-amber-800">
              {preflight.blockers.map((blocker) => (
                <li key={blocker}>• {BLOCKER_LABELS[blocker] || blocker.replaceAll('_', ' ')}</li>
              ))}
            </ul>
          </div>
        )}

        <details className="rounded-xl border border-gray-200" open={Boolean(activeApproval)}>
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-gray-800">
            <span className="inline-flex items-center gap-2">
              <ClipboardCheck className="h-4 w-4 text-slate-600" />
              Exact payload fingerprints
            </span>
          </summary>
          <div className="grid grid-cols-1 gap-2 border-t border-gray-100 p-4 sm:grid-cols-2">
            <ShortHash label="Profile snapshot" value={preflight.profile_snapshot_hash} />
            <ShortHash label="Résumé" value={preflight.resume_hash} />
            <ShortHash label="Cover letter" value={preflight.cover_letter_hash} />
            <ShortHash label="Approved answer policies" value={preflight.answer_payload_hash} />
            <div className="sm:col-span-2">
              <ShortHash label="Combined exact payload" value={preflight.combined_payload_hash} />
            </div>
            <div className="sm:col-span-2 text-xs text-gray-500">
              Résumé: <span className="font-medium text-gray-700">{preflight.resume_filename || 'Unavailable'}</span>
              {' · '}Approved policies: <span className="font-medium text-gray-700">{preflight.policy_count}</span>
              {' · '}Idempotency key: <code className="break-all text-gray-700">{preflight.submission_idempotency_key}</code>
            </div>
          </div>
        </details>

        {latestApproval && (
          <div className="rounded-xl border border-gray-200 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-emerald-600" />
                  <span className="text-sm font-semibold text-gray-900">Latest approval</span>
                  <ApprovalStatus status={latestApproval.status} />
                </div>
                <code className="mt-2 block break-all text-xs text-gray-600">{latestApproval.reference}</code>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                  <span>Issued {new Date(latestApproval.approved_at).toLocaleString()}</span>
                  <span>Expires {new Date(latestApproval.expires_at).toLocaleString()}</span>
                </div>
              </div>
              {activeApproval && (
                <button
                  type="button"
                  onClick={() => revokeApproval.mutate(activeApproval.reference)}
                  disabled={revokeApproval.isPending}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                >
                  {revokeApproval.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                  Revoke approval
                </button>
              )}
            </div>
          </div>
        )}

        {!activeApproval && (
          <div className="space-y-4 rounded-xl border border-gray-200 p-4">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Type the exact target to issue one approval</h3>
              <p className="mt-1 text-xs text-gray-500">
                Values are deliberately not prefilled. Copying the displayed target is an explicit operator action.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="label">Employer</label>
                <input
                  className="input"
                  value={confirmEmployer}
                  onChange={(event) => setConfirmEmployer(event.target.value)}
                  placeholder={preflight.employer}
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="label">Role</label>
                <input
                  className="input"
                  value={confirmRole}
                  onChange={(event) => setConfirmRole(event.target.value)}
                  placeholder={preflight.role}
                  autoComplete="off"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="label">Exact application URL</label>
                <input
                  className="input font-mono text-xs"
                  value={confirmUrl}
                  onChange={(event) => setConfirmUrl(event.target.value)}
                  placeholder={preflight.application_url}
                  autoComplete="off"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="label">Approval note, optional</label>
                <textarea
                  className="input min-h-[72px] resize-none"
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="Why this exact application is approved for the supervised pilot"
                  maxLength={2000}
                />
              </div>
            </div>
            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-3">
              <input
                type="checkbox"
                checked={confirmFinalSubmit}
                onChange={(event) => setConfirmFinalSubmit(event.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-red-300"
              />
              <span className="text-xs leading-relaxed text-red-800">
                I explicitly approve a supervised final-submit attempt for this exact employer, role, URL, résumé, cover letter, and answer-policy payload. I understand challenges and uncertain confirmation still stop for review.
              </span>
            </label>
            <button
              type="button"
              onClick={() => createApproval.mutate()}
              disabled={!canIssue}
              className="btn-primary flex w-full items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {createApproval.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <LockKeyhole className="h-4 w-4" />}
              Issue 20-minute one-time approval
            </button>
            {!exactConfirmationsMatch && (confirmEmployer || confirmRole || confirmUrl) && (
              <p className="text-center text-xs text-amber-700">All three confirmations must match the displayed target exactly.</p>
            )}
          </div>
        )}

        {activeApproval && (
          <div className="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-emerald-900">
              <Timer className="h-4 w-4" />
              One live attempt may be queued before this approval expires
            </div>
            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-emerald-200 bg-white p-3">
              <input
                type="checkbox"
                checked={reviewedHashes}
                onChange={(event) => setReviewedHashes(event.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-emerald-300"
              />
              <span className="text-xs leading-relaxed text-gray-700">
                I rechecked the target and all displayed hashes. No unresolved question, legal declaration, assessment, CAPTCHA, MFA, login, or identity boundary should be automated.
              </span>
            </label>
            <button
              type="button"
              onClick={() => queueSubmission.mutate(activeApproval.reference)}
              disabled={!canQueue}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {queueSubmission.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Queue one supervised submission attempt
            </button>
            {approvalExpiredLocally && (
              <p className="text-center text-xs font-medium text-red-700">This approval has expired. Refresh and issue a new approval.</p>
            )}
          </div>
        )}

        <div className="flex items-start gap-2 rounded-xl bg-slate-100 p-3 text-xs leading-relaxed text-slate-600">
          <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-700" />
          This panel never reveals answer values and cannot promote adapter maturity. A final click without concrete confirmation evidence remains submission uncertain.
        </div>
      </div>
    </section>
  )
}
