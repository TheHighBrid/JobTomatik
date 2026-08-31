import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Power,
  PowerOff,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import api, { getApiErrorMessage } from '../api/client'
import {
  nativeRuntimeBootstrapAvailable,
  updateRuntimeViaNativeBootstrap,
} from '../native/runtimeBootstrap'

function formatExpiry(epochSeconds) {
  if (!epochSeconds) return 'unknown expiry'
  try {
    return new Date(Number(epochSeconds) * 1000).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return 'unknown expiry'
  }
}

export default function CurrentLeverRuntimeControl() {
  const queryClient = useQueryClient()
  const [selectedApplicationId, setSelectedApplicationId] = useState('')
  const [confirmingArm, setConfirmingArm] = useState(false)
  const [confirmingUpdate, setConfirmingUpdate] = useState(false)

  const workspaceQuery = useQuery({
    queryKey: ['current-lever-workspace'],
    queryFn: () => api.get('/supervised-pilot/current-lever'),
    select: (response) => response.data,
    retry: false,
    refetchInterval: 30000,
  })

  const runtimeQuery = useQuery({
    queryKey: ['current-lever-runtime-control'],
    queryFn: () => api.get('/supervised-pilot/current-lever/runtime-control'),
    select: (response) => response.data,
    retry: true,
    retryDelay: 1500,
    refetchInterval: 2500,
  })

  const readyCandidates = useMemo(
    () => (workspaceQuery.data?.candidates || []).filter((candidate) => (
      candidate.automation_state === 'ready_to_apply'
      && (candidate.uncertain_submission_attempt_count || 0) === 0
      && (candidate.active_submission_attempt_count || 0) === 0
    )),
    [workspaceQuery.data],
  )

  const executingSubmissionCount = useMemo(
    () => (workspaceQuery.data?.candidates || []).reduce((total, candidate) => {
      const active = Number(candidate.active_submission_attempt_count || 0)
      const uncertain = Number(candidate.uncertain_submission_attempt_count || 0)
      return total + Math.max(0, active - uncertain)
    }, 0),
    [workspaceQuery.data],
  )

  useEffect(() => {
    if (!selectedApplicationId && readyCandidates.length > 0) {
      setSelectedApplicationId(String(readyCandidates[0].application_id))
      return
    }
    if (
      selectedApplicationId
      && !readyCandidates.some((candidate) => String(candidate.application_id) === selectedApplicationId)
    ) {
      setSelectedApplicationId(readyCandidates[0] ? String(readyCandidates[0].application_id) : '')
      setConfirmingArm(false)
    }
  }, [readyCandidates, selectedApplicationId])

  const refreshControl = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['current-lever-runtime-control'] }),
      queryClient.invalidateQueries({ queryKey: ['current-lever-workspace'] }),
      queryClient.invalidateQueries({ queryKey: ['applications'] }),
    ])
  }

  const runtime = runtimeQuery.data
  const leaseActive = runtime?.lease_active === true
  const canDisarm = runtime?.can_disarm === true
  const transitionState = runtime?.transition_state || 'idle'
  const transitionPending = transitionState === 'requested' || transitionState === 'inflight'
  const uncertain = transitionState === 'uncertain_no_replay'
  const controllerReady = runtime?.controller_available === true
  const available = runtime?.available === true
  const selectedCandidate = readyCandidates.find(
    (candidate) => String(candidate.application_id) === selectedApplicationId,
  )
  const nativeBootstrapSafe = (
    nativeRuntimeBootstrapAvailable()
    && workspaceQuery.isSuccess
    && runtimeQuery.isSuccess
    && !leaseActive
    && !transitionPending
    && executingSubmissionCount === 0
  )

  const armMutation = useMutation({
    mutationFn: (applicationId) => api.post(
      `/supervised-pilot/current-lever/${applicationId}/runtime-control/arm`,
      {
        acknowledgment: `ENABLE LEVER SUPERVISED WINDOW ${applicationId}`,
      },
      { timeout: 15000 },
    ),
    onSuccess: async () => {
      setConfirmingArm(false)
      await refreshControl()
      toast.success('Supervised Lever window requested. JobTomatik will reconnect automatically after the local restart.')
    },
    onError: (error) => toast.error(
      getApiErrorMessage(error, 'Could not request the supervised Lever runtime window.'),
    ),
  })

  const disarmMutation = useMutation({
    mutationFn: () => api.post(
      '/supervised-pilot/current-lever/runtime-control/disarm',
      null,
      { timeout: 15000 },
    ),
    onSuccess: async () => {
      await refreshControl()
      toast.success('Safe runtime restore requested. JobTomatik will reconnect automatically.')
    },
    onError: (error) => toast.error(
      getApiErrorMessage(error, 'Could not request the safe runtime restore.'),
    ),
  })

  const updateMutation = useMutation({
    mutationFn: async () => {
      try {
        const response = await api.post(
          '/controller/android-runtime/update',
          null,
          { timeout: 15000 },
        )
        return { mode: 'controller', result: response.data }
      } catch (error) {
        const status = error?.response?.status
        const endpointMissing = status === 404 || status === 405
        if (!endpointMissing) {
          throw error
        }
        if (!nativeBootstrapSafe) {
          throw new Error(
            'The local backend is older than the in-app updater, but native bootstrap is blocked until runtime state is readable and no Lever submission is executing.',
          )
        }
        const result = await updateRuntimeViaNativeBootstrap()
        return { mode: 'native-bootstrap', result }
      }
    },
    onSuccess: async (result) => {
      setConfirmingUpdate(false)
      await refreshControl()
      if (result?.mode === 'native-bootstrap') {
        toast.success('Native Android bootstrap completed. JobTomatik is now on the verified in-app update path.')
      } else {
        toast.success('Android runtime update requested. JobTomatik will reconnect automatically after the verified restart.')
      }
    },
    onError: (error) => toast.error(
      error?.message || getApiErrorMessage(error, 'Could not request the Android runtime update.'),
    ),
  })

  const updateControlAvailable = available || nativeBootstrapSafe

  return (
    <section className="card overflow-hidden border border-slate-200">
      <div className="border-b border-slate-200 bg-slate-950 px-5 py-4 text-white">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-300" />
              <h2 className="font-semibold">Supervised Lever runtime</h2>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-300">
              Open or close the temporary Android submission window, or safely refresh the local runtime from JobTomatik. This does not approve an application, queue a submission, or enable unattended automation.
            </p>
          </div>
          <div className={`rounded-full border px-3 py-1 text-xs font-semibold ${
            leaseActive
              ? 'border-emerald-400/40 bg-emerald-400/15 text-emerald-200'
              : transitionPending
                ? 'border-amber-400/40 bg-amber-400/15 text-amber-100'
                : 'border-slate-600 bg-slate-800 text-slate-200'
          }`}>
            {leaseActive
              ? `Window active · until ${formatExpiry(runtime?.lease_expires_at_epoch)}`
              : transitionPending
                ? 'Local transition in progress'
                : 'Fail-safe runtime'}
          </div>
        </div>
      </div>

      <div className="space-y-4 p-5">
        {runtimeQuery.isLoading && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Checking native runtime control…
          </div>
        )}

        {runtimeQuery.isError && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <div className="flex items-start gap-2">
              <RefreshCw className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <div>
                JobTomatik may be restarting locally. This panel will keep reconnecting; no control request is replayed automatically.
              </div>
            </div>
          </div>
        )}

        {runtime && !controllerReady && !nativeBootstrapSafe && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <div>
                Native runtime controller is offline. Arm, disarm, and update requests are blocked rather than left unclaimed.
              </div>
            </div>
          </div>
        )}

        {nativeBootstrapSafe && !controllerReady && (
          <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900">
            <div className="flex items-start gap-2">
              <RefreshCw className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <div>
                The installed Android app can perform the one-time native bootstrap because the supervised window is closed and no queued or in-progress Lever submission is executing. Quarantined uncertain applications remain untouched.
              </div>
            </div>
          </div>
        )}

        {uncertain && !leaseActive && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-900">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <div>
                The previous native control action ended without a controller receipt. It will not be replayed. The process-bound lease state shown here is authoritative.
              </div>
            </div>
          </div>
        )}

        {!leaseActive && (
          <div className="rounded-xl border border-sky-200 bg-sky-50 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="max-w-3xl">
                <div className="text-xs font-semibold text-sky-950">Update Android runtime</div>
                <p className="mt-1 text-[11px] leading-relaxed text-sky-800">
                  Pull the latest main revision through the hardened native updater, reinstall the native commands, restart the managed stack, install the exact CI-built frontend artifact, and rerun runtime acceptance. The server blocks this action while a supervised window or queued or in-progress submission is executing. Quarantined uncertain applications remain immutable and are never retried by this maintenance action.
                </p>
              </div>

              {confirmingUpdate ? (
                <div className="min-w-[240px] rounded-lg border border-sky-200 bg-white p-3">
                  <div className="text-xs font-semibold text-sky-950">Update and restart JobTomatik?</div>
                  <p className="mt-1 text-[11px] leading-relaxed text-sky-800">
                    The local app can disconnect while the verified runtime refresh runs. No application approval or submit action is created.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={!updateControlAvailable || transitionPending || updateMutation.isPending}
                      onClick={() => updateMutation.mutate()}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-sky-800 px-3 py-2 text-xs font-semibold text-white hover:bg-sky-900 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {updateMutation.isPending
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <RefreshCw className="h-3.5 w-3.5" />}
                      Confirm runtime update
                    </button>
                    <button
                      type="button"
                      disabled={updateMutation.isPending}
                      onClick={() => setConfirmingUpdate(false)}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  disabled={!updateControlAvailable || transitionPending}
                  onClick={() => setConfirmingUpdate(true)}
                  className="inline-flex min-w-fit items-center justify-center gap-1.5 rounded-lg border border-sky-300 bg-white px-3 py-2 text-xs font-semibold text-sky-950 hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <RefreshCw className="h-3.5 w-3.5" /> Update runtime
                </button>
              )}
            </div>
          </div>
        )}

        {leaseActive ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-700" />
                <div>
                  <div className="text-xs font-semibold text-emerald-950">Process-bound supervised window is active</div>
                  <p className="mt-1 text-[11px] leading-relaxed text-emerald-800">
                    The API and worker must keep their exact attested process identities for this lease to remain valid. Final submission still requires the separate exact application approval in Fresh Runtime Preflight.
                  </p>
                  {!canDisarm && (
                    <p className="mt-2 text-[11px] leading-relaxed text-amber-800">
                      This account does not hold the signed lease-owner receipt, so it cannot revoke another account&apos;s active supervised window.
                    </p>
                  )}
                </div>
              </div>
              <button
                type="button"
                disabled={!canDisarm || !controllerReady || disarmMutation.isPending || transitionPending}
                onClick={() => disarmMutation.mutate()}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {disarmMutation.isPending
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  : <PowerOff className="h-3.5 w-3.5" />}
                Restore fail-safe runtime
              </button>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-xs font-semibold text-slate-900">Open a temporary supervised window</div>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-600">
              Only a ready-to-apply owner-selected Lever application can request the native window. The request expires quickly and is consumed at most once.
            </p>

            {readyCandidates.length === 0 ? (
              <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-[11px] text-slate-600">
                No current Lever application is ready yet. Finish material review and any remaining application blockers first.
              </div>
            ) : (
              <>
                <label className="mt-3 block text-[11px] font-semibold text-slate-700" htmlFor="lever-runtime-application">
                  Ready application
                </label>
                <select
                  id="lever-runtime-application"
                  value={selectedApplicationId}
                  onChange={(event) => {
                    setSelectedApplicationId(event.target.value)
                    setConfirmingArm(false)
                  }}
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900"
                >
                  {readyCandidates.map((candidate) => (
                    <option key={candidate.application_id} value={candidate.application_id}>
                      Application {candidate.application_id} · {candidate.employer} · {candidate.role}
                    </option>
                  ))}
                </select>

                {confirmingArm ? (
                  <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                    <div className="text-xs font-semibold text-amber-950">
                      Enable the supervised runtime window for application {selectedApplicationId}?
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-amber-800">
                      This opens only the short-lived runtime capability. It does not approve or submit {selectedCandidate?.role || 'the application'}.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={!available || armMutation.isPending || !selectedApplicationId}
                        onClick={() => armMutation.mutate(selectedApplicationId)}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {armMutation.isPending
                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : <Power className="h-3.5 w-3.5" />}
                        Confirm supervised window
                      </button>
                      <button
                        type="button"
                        disabled={armMutation.isPending}
                        onClick={() => setConfirmingArm(false)}
                        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    disabled={!available || transitionPending || !selectedApplicationId}
                    onClick={() => setConfirmingArm(true)}
                    className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Power className="h-3.5 w-3.5" /> Enable supervised runtime window
                  </button>
                )}
              </>
            )}
          </div>
        )}

        {runtime?.last_result && (
          <div className="text-[10px] text-slate-500">
            Last native control result: {runtime.last_result.action || 'unknown'} · {runtime.last_result.outcome || 'unknown'}
          </div>
        )}
      </div>
    </section>
  )
}
