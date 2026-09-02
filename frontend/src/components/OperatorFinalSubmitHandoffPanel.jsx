import { useCallback, useEffect, useMemo, useState } from 'react'
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
  XCircle,
} from 'lucide-react'

import {
  bootstrapHandoff,
  cancelHandoff,
  claimHandoff,
  completeHandoff,
  getApiErrorMessage,
  getHandoffFrame,
  heartbeatHandoff,
  listApplicationHandoffs,
  recoverHandoffLease,
  sendHandoffAction,
} from '../api/client'

const ACTIVE_STATUSES = new Set(['awaiting_user', 'claimed', 'ready_to_resume', 'resuming'])

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

  const sessionsQuery = useQuery({
    queryKey: ['handoffs', applicationId],
    queryFn: () => listApplicationHandoffs(applicationId),
    select: (response) => response.data,
    refetchInterval: 4000,
  })

  const session = useMemo(
    () => (sessionsQuery.data || []).find(
      (item) => item.challenge_type === 'final_submit' && ACTIVE_STATUSES.has(item.status),
    ) || null,
    [sessionsQuery.data],
  )

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

  useEffect(() => () => {
    if (frameUrl) URL.revokeObjectURL(frameUrl)
  }, [frameUrl])

  const refreshFrame = useCallback(async (token = leaseToken) => {
    if (!session || !token || session.status !== 'claimed') return
    setIsRefreshing(true)
    try {
      const response = await getHandoffFrame(session.public_id, token)
      const nextUrl = URL.createObjectURL(response.data)
      setFrameUrl((previous) => {
        if (previous) URL.revokeObjectURL(previous)
        return nextUrl
      })
    } catch (error) {
      toast.error(getApiErrorMessage(error, 'Could not load the retained application.'))
    } finally {
      setIsRefreshing(false)
    }
  }, [leaseToken, session])

  useEffect(() => {
    if (leaseToken && session?.status === 'claimed') refreshFrame(leaseToken)
  }, [leaseToken, session?.public_id, session?.status, refreshFrame])

  useEffect(() => {
    if (!leaseToken || !session || session.status !== 'claimed') return undefined
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
  }, [leaseToken, session])

  const openMutation = useMutation({
    mutationFn: async () => {
      const bootstrapped = await bootstrapHandoff(session.public_id)
      return claimHandoff(session.public_id, bootstrapped.data.resume_token)
    },
    onSuccess: async (response) => {
      const token = response.data.lease_token
      writeLease(session.public_id, token)
      setLeaseToken(token)
      await invalidate()
      toast.success('Exact retained application opened in review-only mode.')
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
    mutationFn: () => sendHandoffAction(
      session.public_id,
      leaseToken,
      { action: 'operator_submit' },
    ),
    onSuccess: async (response) => {
      setSubmitActionSent(true)
      await refreshFrame()
      if (response.data?.submission_confirmed) {
        completeMutation.mutate()
      } else {
        toast('Final Submit was activated. Waiting for explicit employer confirmation.')
      }
    },
    onError: (error) => toast.error(getApiErrorMessage(
      error,
      'The exact final Submit action was blocked. Re-prepare rather than guessing.',
    )),
  })

  const cancelMutation = useMutation({
    mutationFn: () => cancelHandoff(
      session.public_id,
      'Cancelled by owner before operator-assisted final submission.',
    ),
    onSuccess: async () => {
      writeLease(session.public_id, '')
      setLeaseToken('')
      await invalidate()
      toast('Retained final-submit handoff cancelled.')
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not cancel the retained handoff.')),
  })

  if (!session) return null

  const claimed = session.status === 'claimed' && Boolean(leaseToken)
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
              This page is locked against answer editing. After exact approval, you may review the filled form and trigger only its verified final Submit control.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-5">
        {session.status === 'awaiting_user' && !leaseToken && (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2 text-sm text-slate-600">
              <LockKeyhole className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-700" />
              <span>Opening is server-locked until the exact operator-assisted approval above is consumed.</span>
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

        {session.status === 'claimed' && !leaseToken && (
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
            <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-950">
              <div className="flex items-center justify-between gap-2 bg-slate-900 px-3 py-2 text-xs text-slate-300">
                <span className="truncate">{session.current_url || 'Exact retained employer form'}</span>
                <button
                  type="button"
                  onClick={() => refreshFrame()}
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
                    alt="Review-only retained application"
                    className="block max-h-[620px] w-full select-none object-contain"
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
                <span>No typing, answer editing, navigation, or arbitrary browser clicks are exposed in this handoff. The backend accepts only the single verified final-submit action.</span>
              </div>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <button
                type="button"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending || submitMutation.isPending}
                className="btn-secondary inline-flex items-center justify-center gap-2 border-red-200 text-red-700 hover:bg-red-50"
              >
                <XCircle className="h-4 w-4" /> Cancel
              </button>
              <div className="flex flex-wrap gap-2">
                {submitActionSent && (
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
                  disabled={submitMutation.isPending || completeMutation.isPending || submitActionSent}
                  className="btn-primary inline-flex items-center gap-2"
                >
                  {submitMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Submit exact application
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
