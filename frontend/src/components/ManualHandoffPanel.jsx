import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle, ArrowLeft, CheckCircle2, Hand, Keyboard, Loader2,
  MailPlus, MousePointer2, RefreshCw, RotateCcw, ShieldCheck, XCircle
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
  submitApplication,
} from '../api/client'

const ACTIVE_STATUSES = new Set(['awaiting_user', 'claimed', 'ready_to_resume', 'resuming'])
const RECOVERABLE_STATUSES = new Set(['expired', 'failed', 'cancelled'])

function leaseKey(publicId) {
  return `jobtomatik_handoff_lease_${publicId}`
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
    // The lease remains in component memory when sessionStorage is unavailable.
  }
}

export default function ManualHandoffPanel({ applicationId }) {
  const qc = useQueryClient()
  const imageRef = useRef(null)
  const [leaseToken, setLeaseToken] = useState('')
  const [frameUrl, setFrameUrl] = useState('')
  const [secretInput, setSecretInput] = useState('')
  const [isRefreshing, setIsRefreshing] = useState(false)

  const { data: sessions = [] } = useQuery({
    queryKey: ['handoffs', applicationId],
    queryFn: () => listApplicationHandoffs(applicationId),
    select: (response) => response.data,
    refetchInterval: 5000,
  })

  const session = useMemo(() => {
    const active = sessions.find((item) => ACTIVE_STATUSES.has(item.status))
    if (active) return active
    const latest = sessions[0]
    return latest && RECOVERABLE_STATUSES.has(latest.status) ? latest : null
  }, [sessions])

  useEffect(() => {
    if (!session || !ACTIVE_STATUSES.has(session.status)) {
      setLeaseToken('')
      return
    }
    setLeaseToken(readLease(session.public_id))
  }, [session?.public_id, session?.status])

  useEffect(() => () => {
    if (frameUrl) URL.revokeObjectURL(frameUrl)
  }, [frameUrl])

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['handoffs', applicationId] })
    qc.invalidateQueries({ queryKey: ['application', String(applicationId)] })
    qc.invalidateQueries({ queryKey: ['application', applicationId] })
  }, [applicationId, qc])

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
      const message = getApiErrorMessage(error, 'Could not load the retained browser')
      if ([403, 409, 410].includes(error?.response?.status)) {
        writeLease(session.public_id, '')
        setLeaseToken('')
      }
      toast.error(message)
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
          toast.error('The secure handoff lease expired. Recover it or start fresh to continue.')
        }
      }
    }, 30000)
    return () => window.clearInterval(timer)
  }, [leaseToken, session])

  const storeLease = (token) => {
    writeLease(session.public_id, token)
    setLeaseToken(token)
    invalidate()
  }

  const openMutation = useMutation({
    mutationFn: async () => {
      const bootstrapped = await bootstrapHandoff(session.public_id)
      const claimed = await claimHandoff(session.public_id, bootstrapped.data.resume_token)
      return claimed.data
    },
    onSuccess: (data) => {
      storeLease(data.lease_token)
      toast.success('Secure handoff opened')
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not open secure handoff')),
  })

  const recoverMutation = useMutation({
    mutationFn: () => recoverHandoffLease(session.public_id),
    onSuccess: (response) => {
      storeLease(response.data.lease_token)
      toast.success('Secure handoff lease recovered')
    },
    onError: (error) => toast.error(getApiErrorMessage(
      error,
      'The previous lease may still be active. Start fresh when the browser session is no longer usable.'
    )),
  })

  const actionMutation = useMutation({
    mutationFn: (action) => sendHandoffAction(session.public_id, leaseToken, action),
    onSuccess: () => {
      refreshFrame()
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Browser action failed')),
  })

  const completeMutation = useMutation({
    mutationFn: () => completeHandoff(session.public_id, leaseToken),
    onSuccess: () => {
      writeLease(session.public_id, '')
      setLeaseToken('')
      setSecretInput('')
      toast.success('Challenge verified. JobTomatik is resuming the application.')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'The challenge is still active')),
  })

  const cancelMutation = useMutation({
    mutationFn: () => cancelHandoff(session.public_id, 'Cancelled from the application screen.'),
    onSuccess: () => {
      writeLease(session.public_id, '')
      setLeaseToken('')
      setSecretInput('')
      toast('Handoff cancelled')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not cancel handoff')),
  })

  const restartMutation = useMutation({
    mutationFn: async () => {
      if (session && ACTIVE_STATUSES.has(session.status)) {
        await cancelHandoff(session.public_id, 'Superseded by a fresh secure handoff.')
      }
      return submitApplication(applicationId, true)
    },
    onSuccess: () => {
      if (session) writeLease(session.public_id, '')
      setLeaseToken('')
      setSecretInput('')
      setFrameUrl((previous) => {
        if (previous) URL.revokeObjectURL(previous)
        return ''
      })
      toast.success('Fresh dry run queued. A new secure handoff will appear when the protected step is reached.')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not start a fresh handoff')),
  })

  if (!session) return null

  const claimed = session.status === 'claimed' && Boolean(leaseToken)
  const waitingForWorker = ['ready_to_resume', 'resuming'].includes(session.status)
  const terminal = RECOVERABLE_STATUSES.has(session.status)
  const challengeLabel = session.challenge_type === 'mfa'
    ? 'MFA verification'
    : session.challenge_type === 'login'
      ? 'Secure sign-in'
      : session.challenge_type === 'anti_bot'
        ? 'Human verification'
        : 'CAPTCHA verification'

  const handleFrameClick = (event) => {
    if (!claimed || actionMutation.isPending) return
    const image = imageRef.current
    const rect = image.getBoundingClientRect()
    const x = (event.clientX - rect.left) * (image.naturalWidth / rect.width)
    const y = (event.clientY - rect.top) * (image.naturalHeight / rect.height)
    actionMutation.mutate({ action: 'click', x, y })
  }

  const submitSecret = () => {
    const value = secretInput.trim()
    if (!value || !claimed) return
    actionMutation.mutate({ action: 'replace_and_submit', text: value }, {
      onSuccess: () => {
        setSecretInput('')
        toast.success('Newest code replaced the old value and was submitted')
      },
    })
  }

  const runRecoveryAction = (action, successMessage) => {
    actionMutation.mutate({ action }, {
      onSuccess: () => toast.success(successMessage),
    })
  }

  if (terminal) {
    return (
      <section className="card overflow-hidden border border-red-200">
        <div className="flex items-start gap-3 bg-red-50 px-5 py-4 border-b border-red-100">
          <div className="w-10 h-10 rounded-xl bg-white flex items-center justify-center text-red-700 shadow-sm flex-shrink-0">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold text-gray-900">Secure handoff ended</h2>
              <span className="badge bg-red-100 text-red-800 text-xs">{session.status.replaceAll('_', ' ')}</span>
            </div>
            <p className="text-sm text-gray-600 mt-1">
              {session.failure_reason || 'The retained verification session is no longer usable.'}
            </p>
          </div>
        </div>
        <div className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <p className="text-sm text-gray-600">
            Start fresh to rebuild the application form and request a new verification code.
          </p>
          <button
            className="btn-primary flex items-center gap-2 justify-center whitespace-nowrap"
            onClick={() => restartMutation.mutate()}
            disabled={restartMutation.isPending}
          >
            {restartMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
            Start fresh handoff
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="card overflow-hidden border border-amber-200">
      <div className="flex items-start gap-3 bg-amber-50 px-5 py-4 border-b border-amber-100">
        <div className="w-10 h-10 rounded-xl bg-white flex items-center justify-center text-amber-700 shadow-sm flex-shrink-0">
          <ShieldCheck className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold text-gray-900">Action required: {challengeLabel}</h2>
            <span className="badge bg-amber-100 text-amber-800 text-xs">{session.status.replaceAll('_', ' ')}</span>
          </div>
          <p className="text-sm text-gray-600 mt-1">
            JobTomatik preserved the filled application and paused before the protected step. Use only the newest code you receive.
          </p>
        </div>
      </div>

      <div className="p-5 space-y-4">
        {session.status === 'awaiting_user' && !leaseToken && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-start gap-2 text-sm text-gray-600">
              <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />
              <span>The resume token is disclosed once and immediately exchanged for a short-lived browser lease.</span>
            </div>
            <button
              className="btn-primary flex items-center gap-2 justify-center whitespace-nowrap"
              onClick={() => openMutation.mutate()}
              disabled={openMutation.isPending}
            >
              {openMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hand className="w-4 h-4" />}
              Open secure handoff
            </button>
          </div>
        )}

        {session.status === 'claimed' && !leaseToken && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl bg-gray-50 p-4">
            <div className="text-sm text-gray-600">
              This tab no longer has the browser lease. Recover it after the previous lease expires, or start fresh immediately.
            </div>
            <div className="flex gap-2 flex-wrap">
              <button
                className="btn-secondary flex items-center gap-2 justify-center whitespace-nowrap"
                onClick={() => recoverMutation.mutate()}
                disabled={recoverMutation.isPending || restartMutation.isPending}
              >
                {recoverMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Recover lease
              </button>
              <button
                className="btn-primary flex items-center gap-2 justify-center whitespace-nowrap"
                onClick={() => restartMutation.mutate()}
                disabled={recoverMutation.isPending || restartMutation.isPending}
              >
                {restartMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
                Start fresh
              </button>
            </div>
          </div>
        )}

        {waitingForWorker && (
          <div className="flex items-center gap-3 rounded-xl bg-blue-50 text-blue-800 p-4">
            <Loader2 className="w-5 h-5 animate-spin flex-shrink-0" />
            <div>
              <div className="font-medium">Challenge completed</div>
              <div className="text-sm text-blue-700">JobTomatik is reconnecting and continuing from the preserved form.</div>
            </div>
          </div>
        )}

        {claimed && (
          <>
            <div className="rounded-xl border border-gray-200 bg-gray-950 overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 bg-gray-900 text-xs text-gray-300">
                <span className="truncate">{session.current_url || 'Retained browser session'}</span>
                <button
                  onClick={() => refreshFrame()}
                  disabled={isRefreshing}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
                  Refresh image
                </button>
              </div>
              <div className="relative min-h-[260px] flex items-center justify-center">
                {frameUrl ? (
                  <img
                    ref={imageRef}
                    src={frameUrl}
                    alt="Secure retained browser"
                    onClick={handleFrameClick}
                    className="block max-h-[620px] w-full object-contain cursor-crosshair select-none"
                    draggable="false"
                  />
                ) : (
                  <Loader2 className="w-7 h-7 animate-spin text-white" />
                )}
                {(actionMutation.isPending || isRefreshing) && (
                  <div className="absolute inset-0 bg-black/25 flex items-center justify-center pointer-events-none">
                    <Loader2 className="w-7 h-7 animate-spin text-white" />
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-wrap gap-2 rounded-xl bg-gray-50 p-3">
              <button
                className="btn-secondary text-xs flex items-center gap-1.5"
                onClick={() => runRecoveryAction('resend_code', 'A new verification code was requested')}
                disabled={actionMutation.isPending}
              >
                <MailPlus className="w-3.5 h-3.5" />
                Request new code
              </button>
              <button
                className="btn-secondary text-xs flex items-center gap-1.5"
                onClick={() => runRecoveryAction('back', 'Returned to the previous verification page')}
                disabled={actionMutation.isPending}
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Go back
              </button>
              <button
                className="btn-secondary text-xs flex items-center gap-1.5"
                onClick={() => runRecoveryAction('reload', 'Verification page reloaded')}
                disabled={actionMutation.isPending}
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Reload page
              </button>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={secretInput}
                  onChange={(event) => setSecretInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') submitSecret()
                  }}
                  className="input flex-1"
                  placeholder="Paste the newest MFA or verification code"
                  autoComplete="one-time-code"
                  autoCapitalize="none"
                  spellCheck="false"
                />
                <button
                  className="btn-primary flex items-center gap-2"
                  onClick={submitSecret}
                  disabled={!secretInput.trim() || actionMutation.isPending}
                >
                  <Keyboard className="w-4 h-4" />
                  Replace and submit
                </button>
              </div>
              <div className="flex gap-2 flex-wrap">
                {['Tab', 'Shift+Tab', 'Enter', 'Escape', 'Backspace'].map((key) => (
                  <button
                    key={key}
                    className="btn-secondary text-xs"
                    onClick={() => actionMutation.mutate({ action: 'key', key })}
                    disabled={actionMutation.isPending}
                  >
                    {key}
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-blue-100 bg-blue-50 p-3 text-xs text-blue-800">
              Replace and submit clears any expired code already in the focused field, types the newest code, and presses Enter in one action.
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <MousePointer2 className="w-3.5 h-3.5" />
                Click directly on the browser image. Typed values are never written to the audit log.
              </div>
              <div className="flex gap-2 flex-wrap">
                <button
                  className="btn-secondary text-red-600 border-red-200 hover:bg-red-50 flex items-center gap-1.5"
                  onClick={() => cancelMutation.mutate()}
                  disabled={cancelMutation.isPending || restartMutation.isPending}
                >
                  <XCircle className="w-4 h-4" />
                  Cancel
                </button>
                <button
                  className="btn-secondary flex items-center gap-1.5"
                  onClick={() => restartMutation.mutate()}
                  disabled={restartMutation.isPending || cancelMutation.isPending}
                >
                  {restartMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
                  Start over
                </button>
                <button
                  className="btn-primary flex items-center gap-1.5"
                  onClick={() => completeMutation.mutate()}
                  disabled={completeMutation.isPending}
                >
                  {completeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                  I completed the challenge
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
