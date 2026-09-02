import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  CheckCircle2,
  FileCheck2,
  Fingerprint,
  Loader2,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'

import {
  getApiErrorMessage,
  getTaskStatus,
  listSupervisedSubmissionApprovals,
} from '../api/client'
import {
  authorizeOperatorFinalClick,
  createOperatorAssistedApproval,
  getOperatorAssistedPreflight,
  prepareOperatorAssistedSubmission,
} from '../api/operatorAssisted'
import { isApplicationTaskTerminal } from '../applicationTaskRuntime'
import { shortHash, supervisedBlockerLabel } from '../supervisedPlatforms'

const OPERATOR_APPROVAL_SOURCE = 'authenticated_user_operator_assisted'

function HashCard({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <code className="mt-1 block break-all text-[11px] text-slate-700">{shortHash(value)}</code>
    </div>
  )
}

export default function OperatorAssistedSubmissionPanel({ application }) {
  const applicationId = application?.id
  const queryClient = useQueryClient()
  const [confirmation, setConfirmation] = useState('')
  const [prepareTaskId, setPrepareTaskId] = useState('')

  const preflightQuery = useQuery({
    queryKey: ['operator-assisted-preflight', applicationId],
    queryFn: () => getOperatorAssistedPreflight(applicationId),
    select: (response) => response.data,
    enabled: Boolean(applicationId),
    retry: false,
    refetchInterval: prepareTaskId ? 2000 : false,
    refetchOnWindowFocus: true,
  })

  const approvalsQuery = useQuery({
    queryKey: ['supervised-approvals', applicationId],
    queryFn: () => listSupervisedSubmissionApprovals(applicationId),
    select: (response) => response.data,
    enabled: Boolean(applicationId),
    retry: false,
  })

  const taskQuery = useQuery({
    queryKey: ['operator-assisted-prepare-task', prepareTaskId],
    queryFn: () => getTaskStatus(prepareTaskId),
    select: (response) => response.data,
    enabled: Boolean(prepareTaskId),
    refetchInterval: (query) => (
      isApplicationTaskTerminal(query.state.data?.status) ? false : 1500
    ),
    refetchIntervalInBackground: true,
    retry: 2,
  })

  const preflight = preflightQuery.data
  const operatorApprovals = useMemo(
    () => (approvalsQuery.data || []).filter(
      (approval) => approval?.approval_metadata?.approval_source === OPERATOR_APPROVAL_SOURCE,
    ),
    [approvalsQuery.data],
  )
  const latestOperatorApproval = operatorApprovals[0] || null
  const exactHandoffApproved = Boolean(
    latestOperatorApproval
    && preflight?.operator_handoff_public_id
    && latestOperatorApproval.approval_metadata?.handoff_public_id === preflight.operator_handoff_public_id
  )
  const finalClickUnlocked = Boolean(
    exactHandoffApproved && latestOperatorApproval.status === 'consumed'
  )

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['operator-assisted-preflight', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['supervised-approvals', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['handoffs', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['application', String(applicationId)] }),
      queryClient.invalidateQueries({ queryKey: ['application', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['applications'] }),
    ])
  }

  useEffect(() => {
    if (!prepareTaskId || !taskQuery.data || !isApplicationTaskTerminal(taskQuery.data.status)) return
    const result = taskQuery.data.result || {}
    setPrepareTaskId('')
    refreshAll()
    if (taskQuery.data.status === 'SUCCESS' && result.handoff_public_id) {
      toast.success('Filled application retained. Exact owner approval is now required.')
    } else if (taskQuery.data.status === 'SUCCESS' && result.requires_manual_review) {
      toast.error(result.error || 'Preparation reached a different manual-review boundary.')
    } else if (taskQuery.data.status !== 'SUCCESS') {
      toast.error(result.error || `Preparation ended with ${taskQuery.data.status}.`)
    }
  }, [prepareTaskId, taskQuery.data])

  useEffect(() => {
    setConfirmation('')
  }, [applicationId, preflight?.combined_payload_hash, preflight?.operator_handoff_public_id])

  const prepareMutation = useMutation({
    mutationFn: () => prepareOperatorAssistedSubmission(applicationId),
    onSuccess: async (response) => {
      if (response.data?.handoff_public_id) {
        await refreshAll()
        toast.success('The exact filled application is already retained.')
        return
      }
      const taskId = response.data?.task_id
      if (!taskId) {
        toast.error('The backend did not return the preparation task ID.')
        return
      }
      setPrepareTaskId(taskId)
      toast('Preparing the exact filled application. Final submit remains locked.')
    },
    onError: (error) => toast.error(
      getApiErrorMessage(error, 'Operator-assisted preparation is blocked.'),
    ),
  })

  const approveAndUnlockMutation = useMutation({
    mutationFn: async () => {
      const created = await createOperatorAssistedApproval(applicationId, {
        handoff_public_id: preflight.operator_handoff_public_id,
        confirm_employer: preflight.employer,
        confirm_role: preflight.role,
        confirm_application_url: preflight.application_url,
        confirm_operator_final_click: true,
        expires_in_minutes: 20,
        notes: 'Exact operator-assisted Phase B approval from JobTomatik application UI',
      })
      return authorizeOperatorFinalClick(applicationId, created.data.reference)
    },
    onSuccess: async () => {
      setConfirmation('')
      await refreshAll()
      toast.success('Exact final action unlocked for this retained application only.')
    },
    onError: async (error) => {
      await refreshAll()
      toast.error(getApiErrorMessage(error, 'Exact operator approval could not be completed.'))
    },
  })

  if (preflightQuery.isLoading) {
    return (
      <section className="card p-5">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking operator-assisted Phase B path…
        </div>
      </section>
    )
  }
  if (preflightQuery.isError || !preflight || preflight.platform !== 'lever') return null

  const expectedConfirmation = `SUBMIT ${preflight.employer} | ${preflight.role} | ${preflight.application_url}`
  const confirmationMatches = confirmation === expectedConfirmation
  const preparing = prepareMutation.isPending || Boolean(prepareTaskId)
  const boundaryReady = Boolean(preflight.operator_final_submit_boundary && preflight.operator_handoff_public_id)
  const executionAuthorityOff = (
    preflight.automated_submission_authorized === false
    && preflight.queue_submission_authorized === false
  )
  const canPrepare = Boolean(
    preflight.ready
    && executionAuthorityOff
    && !boundaryReady
    && !preparing
  )
  const canApprove = Boolean(
    preflight.ready
    && executionAuthorityOff
    && boundaryReady
    && !finalClickUnlocked
    && confirmationMatches
    && !approveAndUnlockMutation.isPending
  )

  return (
    <section className="card overflow-hidden border border-emerald-200">
      <div className="border-b border-emerald-200 bg-emerald-950 px-5 py-4 text-white">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-300" />
              <h2 className="font-semibold">Operator-assisted Lever Phase B</h2>
            </div>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-emerald-100/80">
              JobTomatik fills and retains the exact application. Automated final submit stays disabled. You authorize one exact retained payload, then perform the single final action from the secure handoff.
            </p>
          </div>
          <button
            type="button"
            onClick={() => preflightQuery.refetch()}
            disabled={preflightQuery.isFetching}
            className="rounded-lg border border-white/20 p-2 text-emerald-100 hover:bg-white/10 disabled:opacity-50"
            aria-label="Refresh operator-assisted preflight"
          >
            <RefreshCw className={`h-4 w-4 ${preflightQuery.isFetching ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="space-y-4 p-5">
        <div className="grid gap-2 sm:grid-cols-5">
          {[
            ['Global live submit', preflight.global_live_submit_enabled === false],
            ['Lever automated pilot', preflight.platform_pilot_enabled === false],
            ['Autopilot', preflight.autopilot_enabled === false],
            ['Automated submit authority', preflight.automated_submission_authorized === false],
            ['Queue submit authority', preflight.queue_submission_authorized === false],
          ].map(([label, safelyOff]) => (
            <div key={label} className={`rounded-xl border p-3 ${
              safelyOff
                ? 'border-emerald-100 bg-emerald-50'
                : 'border-red-200 bg-red-50'
            }`}>
              <div className={`flex items-center gap-1.5 text-xs font-semibold ${
                safelyOff ? 'text-emerald-900' : 'text-red-900'
              }`}>
                <LockKeyhole className="h-3.5 w-3.5" /> {safelyOff ? 'OFF' : 'BLOCKED'}
              </div>
              <div className={`mt-1 text-[11px] ${
                safelyOff ? 'text-emerald-700' : 'text-red-700'
              }`}>{label}</div>
            </div>
          ))}
        </div>

        {!executionAuthorityOff && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            Operator-assisted actions are disabled because the backend did not explicitly prove automated submission and queue authority are both OFF.
          </div>
        )}

        {!preflight.ready && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
              <AlertTriangle className="h-4 w-4" /> This application is not ready for operator-assisted preparation
            </div>
            <ul className="mt-2 space-y-1 text-xs text-amber-800">
              {(preflight.blockers || []).map((blocker) => (
                <li key={blocker}>• {supervisedBlockerLabel(blocker, preflight.platform)}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-start gap-3">
            <Fingerprint className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-700" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-900">Exact target</div>
              <div className="mt-1 text-sm text-slate-800">{preflight.role}</div>
              <div className="text-xs text-slate-600">{preflight.employer}</div>
              <div className="mt-2 break-all text-[11px] text-slate-500">{preflight.application_url}</div>
            </div>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <HashCard label="Combined payload" value={preflight.combined_payload_hash} />
            <HashCard label="Target identity" value={preflight.target_identity_hash} />
            <HashCard label="Résumé" value={preflight.resume_hash} />
            <HashCard label="Cover letter" value={preflight.cover_letter_hash} />
          </div>
        </div>

        {!boundaryReady && (
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
            <div className="flex items-start gap-3">
              <FileCheck2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-700" />
              <div className="flex-1">
                <div className="text-sm font-semibold text-blue-950">1. Prepare and retain the filled application</div>
                <p className="mt-1 text-xs leading-relaxed text-blue-800">
                  This is fill-only. JobTomatik will stop before final Submit and retain the exact browser page for your review.
                </p>
                <button
                  type="button"
                  onClick={() => prepareMutation.mutate()}
                  disabled={!canPrepare}
                  className="btn-primary mt-3 inline-flex items-center gap-2"
                >
                  {preparing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />}
                  {preparing ? 'Preparing filled application…' : 'Prepare filled application'}
                </button>
              </div>
            </div>
          </div>
        )}

        {boundaryReady && !finalClickUnlocked && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-start gap-3">
              <LockKeyhole className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-700" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-amber-950">2. Approve this exact retained application</div>
                <p className="mt-1 text-xs leading-relaxed text-amber-800">
                  Type the full phrase exactly. This approval unlocks only handoff <code>{preflight.operator_handoff_public_id}</code>. It does not enable automatic submission or queue a live worker.
                </p>
                <code className="mt-3 block break-all rounded-lg bg-slate-950 p-3 text-[11px] leading-relaxed text-white">
                  {expectedConfirmation}
                </code>
                <textarea
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  className="input mt-3 min-h-[88px] resize-none font-mono text-xs"
                  placeholder="Type the exact confirmation phrase"
                  spellCheck="false"
                />
                <button
                  type="button"
                  onClick={() => approveAndUnlockMutation.mutate()}
                  disabled={!canApprove}
                  className="btn-primary mt-3 inline-flex items-center gap-2"
                >
                  {approveAndUnlockMutation.isPending
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <ShieldCheck className="h-4 w-4" />}
                  Approve exact application & unlock final submit
                </button>
              </div>
            </div>
          </div>
        )}

        {finalClickUnlocked && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-700" />
              <div>
                <div className="text-sm font-semibold text-emerald-950">3. Exact final action unlocked</div>
                <p className="mt-1 text-xs leading-relaxed text-emerald-800">
                  Open the secure retained handoff below, review the filled employer form, then use its single “Submit exact application” action. All editing controls remain locked.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
