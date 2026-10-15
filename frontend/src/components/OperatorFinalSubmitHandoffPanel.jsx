import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Send,
  ShieldCheck,
} from 'lucide-react'

import {
  bootstrapHandoff,
  claimHandoff,
  completeHandoff,
  getApiErrorMessage,
  getHandoffFrame,
  getHandoffCapabilities,
  heartbeatHandoff,
  listApplicationHandoffs,
  listSupervisedSubmissionApprovals,
  recoverHandoffLease,
  sendHandoffAction,
} from '../api/client'
import {
  authorizeOperatorFinalClick, createOperatorAssistedApproval,
  getOperatorAssistedPreflight, submitOperatorAssistedFinalAction,
} from '../api/operatorAssisted'
import { handoffExpired, handoffPointer } from '../utils/handoffViewport'

const ACTIVE_STATUSES = new Set(['awaiting_user', 'claimed', 'ready_to_resume', 'resuming'])
const OPERATOR_APPROVAL_SOURCE = 'authenticated_user_operator_assisted'

function leaseKey(publicId) {
  return `jobtomatik_operator_final_lease_${publicId}`
}

function readLease(publicId) {
  try {
    return window.sessionStorage.getItem(leaseKey(publicId)) || ''
  } catch {
    return ''
  }
}

function writeLease(publicId, value) {
  try {
    if (value) window.sessionStorage.setItem(leaseKey(publicId), value)
    else window.sessionStorage.removeItem(leaseKey(publicId))
  } catch {
    // Keep the lease in component memory when storage is unavailable.
  }
}

export default function OperatorFinalSubmitHandoffPanel({ applicationId }) {
  const queryClient = useQueryClient()
  const [leaseToken, setLeaseToken] = useState('')
  const [frameUrl, setFrameUrl] = useState('')
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [submitActionSent, setSubmitActionSent] = useState(false)
  const [frameError, setFrameError] = useState('')
  const [ownerConsent, setOwnerConsent] = useState(false)
  const frameInFlight = useRef(false)
  const activeSession = useRef(null)
  const passiveConfirmationCheck = useRef(false)

  const sessionsQuery = useQuery({
    queryKey: ['handoffs', applicationId],
    queryFn: () => listApplicationHandoffs(applicationId),
    select: (response) => response.data,
    refetchInterval: 4000,
  })

  const session = useMemo(
    () => (sessionsQuery.data || []).find((item) => item.challenge_type === 'final_submit') || null,
    [sessionsQuery.data],
  )
  activeSession.current = session?.public_id
  const expired = handoffExpired(session)
  const interactive = session?.status === 'claimed' && !expired && Boolean(leaseToken)
  const capabilitiesQuery = useQuery({
    queryKey: ['handoff-capabilities', session?.public_id, leaseToken],
    queryFn: async () => (await getHandoffCapabilities(session.public_id, leaseToken)).data,
    enabled: interactive,
    retry: false,
    refetchInterval: (query) => query.state.error ? false : 4000,
  })
  const capabilities = capabilitiesQuery.data
  const browserReady = interactive && Boolean(frameUrl) && !capabilitiesQuery.isError && capabilities?.browser_connected && !frameError

  const approvalsQuery = useQuery({
    queryKey: ['supervised-approvals', applicationId],
    queryFn: () => listSupervisedSubmissionApprovals(applicationId),
    select: (response) => response.data,
    enabled: Boolean(applicationId),
    refetchInterval: 4000,
  })

  const boundApproval = useMemo(
    () => (approvalsQuery.data || []).find((approval) => (
      approval?.approval_metadata?.approval_source === OPERATOR_APPROVAL_SOURCE
      && approval?.approval_metadata?.handoff_public_id === session?.public_id
    )) || null,
    [approvalsQuery.data, session?.public_id],
  )
  const handoffUnlocked = boundApproval?.status === 'consumed'
  const serverFinalActionStarted = Boolean(
    boundApproval?.approval_metadata?.operator_submit_action_started_at,
  )
  const finalActionStarted = submitActionSent || serverFinalActionStarted
  const preflightQuery = useQuery({
    queryKey: ['operator-assisted-preflight', applicationId],
    queryFn: async () => (await getOperatorAssistedPreflight(applicationId)).data,
    enabled: Boolean(session) && !expired && !handoffUnlocked,
    retry: false,
  })
  const preflight = preflightQuery.data

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['handoffs', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['application', String(applicationId)] }),
      queryClient.invalidateQueries({ queryKey: ['application', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['operator-assisted-preflight', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['supervised-approvals', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['submission-evidence', applicationId] }),
      queryClient.invalidateQueries({ queryKey: ['applications'] }),
    ])
  }, [applicationId, queryClient])

  useEffect(() => {
    if (!session) {
      setLeaseToken('')
      setSubmitActionSent(false)
      return
    }
    setLeaseToken(readLease(session.public_id))
  }, [session?.public_id, session?.status])

  useEffect(() => {
    setFrameUrl('')
    setFrameError('')
    setSubmitActionSent(false)
    setOwnerConsent(false)
  }, [session?.public_id])

  useEffect(() => () => {
    if (frameUrl) URL.revokeObjectURL(frameUrl)
  }, [frameUrl])

  const refreshFrame = useCallback(async (token = leaseToken) => {
    if (!session || !token || session.status !== 'claimed' || expired || frameInFlight.current) return
    const publicId = session.public_id
    frameInFlight.current = true
    setIsRefreshing(true)
    try {
      const response = await getHandoffFrame(session.public_id, token)
      if (activeSession.current !== publicId) return
      const nextUrl = URL.createObjectURL(response.data)
      setFrameUrl((previous) => {
        if (previous) URL.revokeObjectURL(previous)
        return nextUrl
      })
      setFrameError('')
    } catch (error) {
      if (activeSession.current === publicId) setFrameError(getApiErrorMessage(error, 'The retained browser is unavailable. Preserve its evidence before recovery.'))
    } finally {
      frameInFlight.current = false
      setIsRefreshing(false)
    }
  }, [leaseToken, session?.public_id, session?.status, expired])

  useEffect(() => {
    if (leaseToken && session?.status === 'claimed') refreshFrame(leaseToken)
  }, [leaseToken, session?.public_id, session?.status, refreshFrame])

  useEffect(() => {
    if (!browserReady) return undefined
    const timer = window.setInterval(() => refreshFrame(), 2000)
    return () => window.clearInterval(timer)
  }, [browserReady, refreshFrame])

  useEffect(() => {
    if (!leaseToken || !session || session.status !== 'claimed' || expired) return undefined
    const timer = window.setInterval(async () => {
      try {
        await heartbeatHandoff(session.public_id, leaseToken)
      } catch (error) {
        if ([403, 409, 410].includes(error?.response?.status)) {
          writeLease(session.public_id, '')
          setLeaseToken('')
        }
      }
    }, 30000)
    return () => window.clearInterval(timer)
  }, [leaseToken, session?.public_id, session?.status, expired])

  const actionMutation = useMutation({
    mutationFn: (action) => sendHandoffAction(session.public_id, leaseToken, action),
    onSuccess: async () => { await refreshFrame(); await capabilitiesQuery.refetch() },
    onError: (error) => toast.error(getApiErrorMessage(error, 'The owner browser action was blocked.')),
  })
  const handleFrameClick = (event) => {
    if (!browserReady || !capabilities?.owner_pointer_enabled || actionMutation.isPending || submitMutation.isPending) return
    const point = handoffPointer(event.currentTarget, event.clientX, event.clientY)
    if (point) actionMutation.mutate({ action: 'click', ...point })
  }

  const openMutation = useMutation({
    mutationFn: async () => {
      let bootstrapped
      try {
        bootstrapped = await bootstrapHandoff(session.public_id)
      } catch (error) {
        if (error?.response?.status === 409 && /already been disclosed/i.test(getApiErrorMessage(error, ''))) return recoverHandoffLease(session.public_id)
        throw error
      }
      return claimHandoff(session.public_id, bootstrapped.data.resume_token)
    },
    onSuccess: async (response) => {
      const token = response.data.lease_token
      writeLease(session.public_id, token)
      setLeaseToken(token)
      await invalidate()
      toast.success('Exact retained application opened for owner verification.')
    },
    onError: (error) => toast.error(getApiErrorMessage(
      error,
      'Exact owner approval is required before this retained application can be opened.',
    )),
  })

  const recoverMutation = useMutation({
    mutationFn: () => recoverHandoffLease(session.public_id),
    onSuccess: async (response) => {
      const token = response.data.lease_token
      writeLease(session.public_id, token)
      setLeaseToken(token)
      await invalidate()
      toast.success('Final-submit review lease recovered.')
    },
    onError: (error) => toast.error(getApiErrorMessage(
      error,
      'The prior review lease is still active. Reopen this screen after it expires.',
    )),
  })

  const approvalMutation = useMutation({
    mutationFn: async () => {
      if (!ownerConsent || !preflight?.ready || preflight.operator_handoff_public_id !== session.public_id) throw new Error('Review and authorize this exact application first.')
      const issued = await createOperatorAssistedApproval(applicationId, {
        handoff_public_id: session.public_id,
        confirm_employer: preflight.employer,
        confirm_role: preflight.role,
        confirm_application_url: preflight.application_url,
        confirm_operator_final_click: true,
      })
      return authorizeOperatorFinalClick(applicationId, issued.data.reference)
    },
    onSuccess: async () => {
      setOwnerConsent(false)
      await invalidate()
      openMutation.mutate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'The exact application could not be approved.')),
  })

  const completeMutation = useMutation({
    mutationFn: () => completeHandoff(session.public_id, leaseToken),
    onSuccess: async () => {
      writeLease(session.public_id, '')
      setLeaseToken('')
      setSubmitActionSent(false)
      await invalidate()
      toast.success('Employer confirmation verified. Submission evidence is being finalized.')
    },
    onError: (error) => toast.error(getApiErrorMessage(
      error,
      'Employer confirmation is not visible yet. Refresh the retained page and verify again.',
    )),
  })

  const submitMutation = useMutation({
    mutationFn: () => submitOperatorAssistedFinalAction(
      applicationId,
      session.public_id,
      leaseToken,
    ),
    onSuccess: async (response) => {
      setSubmitActionSent(true)
      await invalidate()
      await refreshFrame()
      if (response.data?.submission_confirmed) {
        completeMutation.mutate()
      } else {
        toast('Final Submit was activated once. Waiting for explicit employer confirmation.')
      }
    },
    onError: async (error) => {
      const message = getApiErrorMessage(
        error,
        'The exact final Submit action was blocked.',
      )
      const noRetry = /automatic retry is forbidden|already requested|outcome is uncertain/i.test(message)
      if (noRetry) {
        setSubmitActionSent(true)
        await invalidate()
        await refreshFrame()
        toast.error(`${message} Do not submit again; verify the employer page instead.`)
        return
      }
      toast.error(message)
    },
  })

  useEffect(() => {
    if (
      !session
      || session.status !== 'claimed'
      || !leaseToken
      || !handoffUnlocked
      || !interactive
      || capabilitiesQuery.isError
    ) return undefined

    let cancelled = false

    const verifyRetainedConfirmation = async () => {
      if (passiveConfirmationCheck.current) return
      passiveConfirmationCheck.current = true
      try {
        await completeHandoff(session.public_id, leaseToken)
        if (cancelled) return

        writeLease(session.public_id, '')
        setLeaseToken('')
        setSubmitActionSent(false)
        await invalidate()
        toast.success('Employer confirmation detected automatically. Application evidence is being finalized.')
      } catch (error) {
        const status = error?.response?.status
        if ([403, 410].includes(status)) {
          writeLease(session.public_id, '')
          setLeaseToken('')
          await invalidate()
        }
        // 409 means the exact retained page is still pre-submit or confirmation is
        // not yet strong enough. That is the normal polling state and stays silent.
      } finally {
        passiveConfirmationCheck.current = false
      }
    }

    verifyRetainedConfirmation()
    const timer = window.setInterval(verifyRetainedConfirmation, 4000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [
    handoffUnlocked,
    invalidate,
    leaseToken,
    session?.public_id,
    session?.status,
    interactive,
    capabilitiesQuery.isError,
  ])

  if (!session) return null

  const claimed = interactive
  const waitingForEvidence = ['ready_to_resume', 'resuming'].includes(session.status)

  return (
    <section className="card overflow-hidden border border-emerald-200">
      <div className="border-b border-emerald-200 bg-emerald-50 px-5 py-4">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-700" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold text-emerald-950">Secure retained final-submit page</h2>
              <span className="rounded-full border border-emerald-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
                {session.status.replaceAll('_', ' ')}
              </span>
            </div>
            <p className="mt-1 text-sm leading-relaxed text-emerald-900/80">
              Review the live application below. You can scroll and click verification widgets yourself. Answers remain locked; Submit is a separate, once-only action.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-5">
        {(expired || !ACTIVE_STATUSES.has(session.status)) && session.status !== 'completed' && (
          <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
            {session.failure_reason || 'This handoff has expired or stopped. Its evidence and approval are preserved. Review the application recovery state before preparing a new session.'}
          </div>
        )}
        {session.status === 'completed' && <p className="text-sm text-emerald-800">Employer confirmation verified. This handoff is complete.</p>}
        {session.status === 'awaiting_user' && !expired && !leaseToken && !handoffUnlocked && (
          <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
            <p className="font-semibold">Authorize this exact application</p>
            {preflight && <div><p>{preflight.employer}</p><p className="font-semibold">{preflight.role}</p><p className="break-all text-xs">{preflight.application_url}</p></div>}
            <p>Approval opens the retained form for review. The separate Submit button sends the application once.</p>
            {preflightQuery.isError && <p role="alert">{getApiErrorMessage(preflightQuery.error, 'Could not verify this application.')}</p>}
            {preflight?.blockers?.length > 0 && <p role="alert">{preflight.blockers.join(', ')}</p>}
            <label className="flex items-start gap-2"><input type="checkbox" checked={ownerConsent} onChange={(event) => setOwnerConsent(event.target.checked)} disabled={!preflight?.ready || approvalMutation.isPending} /><span>I authorize one submission for this exact employer and role.</span></label>
            <button type="button" className="btn-primary" disabled={!ownerConsent || !preflight?.ready || approvalMutation.isPending || openMutation.isPending} onClick={() => approvalMutation.mutate()}>
              {approvalMutation.isPending || openMutation.isPending ? 'Opening approved application…' : 'Approve and open application'}
            </button>
          </div>
        )}

        {session.status === 'awaiting_user' && !expired && !leaseToken && handoffUnlocked && (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2 text-sm text-slate-600">
              <LockKeyhole className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-700" />
              <span>Open the approved application in its retained browser session.</span>
            </div>
            <button
              type="button"
              className="btn-primary inline-flex items-center justify-center gap-2"
              onClick={() => openMutation.mutate()}
              disabled={openMutation.isPending}
            >
              {openMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />}
              Open retained application
            </button>
          </div>
        )}

        {session.status === 'claimed' && !expired && !leaseToken && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-start gap-2 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>This tab no longer has the short-lived review lease.</span>
            </div>
            <button
              type="button"
              onClick={() => recoverMutation.mutate()}
              disabled={recoverMutation.isPending}
              className="btn-secondary mt-3 inline-flex items-center gap-2"
            >
              {recoverMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Recover review lease
            </button>
          </div>
        )}

        {waitingForEvidence && (
          <div className="flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-900">
            <Loader2 className="mt-0.5 h-5 w-5 animate-spin flex-shrink-0" />
            <div>
              <div className="font-semibold">Employer confirmation verified</div>
              <div className="mt-1 text-sm">JobTomatik is binding the observed confirmation to the consumed exact approval and evidence review pipeline.</div>
            </div>
          </div>
        )}

        {claimed && (
          <>
            {(frameError || capabilitiesQuery.isError || capabilities?.blocked_reason) && (
              <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
                {frameError || capabilities?.blocked_reason || getApiErrorMessage(capabilitiesQuery.error, 'The retained browser is unavailable. Review its recovery state.')}
              </div>
            )}
            <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-950">
              <div className="flex items-center justify-between gap-2 bg-slate-900 px-3 py-2 text-xs text-slate-300">
                <span className="truncate">{session.current_url || 'Exact retained employer form'}</span>
                <button
                  type="button"
                  onClick={() => { refreshFrame(); capabilitiesQuery.refetch() }}
                  disabled={isRefreshing}
                  className="inline-flex items-center gap-1.5 hover:text-white disabled:opacity-50"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
                  Refresh review
                </button>
              </div>
              <div className="flex min-h-[260px] items-center justify-center">
                {frameUrl ? (
                  <img
                    src={frameUrl}
                    alt="Live retained application. Click verification widgets to interact."
                    onClick={handleFrameClick}
                    className="block h-auto max-h-[620px] max-w-full select-none object-contain"
                    draggable="false"
                  />
                ) : (
                  <Loader2 className="h-7 w-7 animate-spin text-white" />
                )}
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-start gap-2 text-xs leading-relaxed text-slate-700">
                <LockKeyhole className="mt-0.5 h-4 w-4 flex-shrink-0" />
                <span>Only verification widgets accept owner clicks. No typing, answer editing, navigation, arbitrary browser clicks, or automatic retry are allowed. Submit is recorded once before touching the employer control.</span>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2">
              {[-450, 450].map((delta) => (
                <button type="button" key={delta} className="btn-secondary" disabled={!browserReady || actionMutation.isPending || submitMutation.isPending} onClick={() => actionMutation.mutate({ action: 'scroll', delta_y: delta })}>
                  {delta < 0 ? 'Scroll up' : 'Scroll down'}
                </button>
              ))}
              {finalActionStarted && (
                <button
                  type="button"
                  onClick={() => completeMutation.mutate()}
                  disabled={completeMutation.isPending}
                  className="btn-secondary inline-flex items-center gap-2"
                >
                  {completeMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Verify employer confirmation
                </button>
              )}
              <button
                type="button"
                onClick={() => submitMutation.mutate()}
                disabled={!browserReady || !capabilities?.submit_available || actionMutation.isPending || submitMutation.isPending || completeMutation.isPending || finalActionStarted}
                className="btn-primary inline-flex items-center gap-2"
              >
                {submitMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {finalActionStarted ? 'Final submit already requested' : 'Submit exact application once'}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
