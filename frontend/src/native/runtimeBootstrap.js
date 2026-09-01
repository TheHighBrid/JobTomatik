import { Capacitor, registerPlugin } from '@capacitor/core'
import api from '../api/client'

const NativeRuntimeBootstrap = registerPlugin('NativeRuntimeBootstrap')
const QUIESCE_STATUS_ATTEMPTS = 15
const QUIESCE_STATUS_INTERVAL_MS = 1000

export function nativeRuntimeBootstrapAvailable() {
  // Plugin availability is the authoritative signal here. The Android WebView can
  // reconnect across a local static-runtime refresh, while URL/platform heuristics
  // may briefly look web-like. A normal browser has no registered native plugin, so
  // this remains false outside the installed APK.
  return Capacitor.isPluginAvailable('NativeRuntimeBootstrap')
}

function requireNativeBootstrap() {
  if (!nativeRuntimeBootstrapAvailable()) {
    throw new Error('Native Android runtime bootstrap is unavailable on this platform.')
  }
}

function executingSubmissionCount(workspace) {
  return (workspace?.candidates || []).reduce((total, candidate) => {
    const active = Number(candidate.active_submission_attempt_count || 0)
    const uncertain = Number(candidate.uncertain_submission_attempt_count || 0)
    return total + Math.max(0, active - uncertain)
  }, 0)
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function readQuiescedSafetyState() {
  let lastRuntime = null
  let lastWorkspace = null

  for (let attempt = 0; attempt < QUIESCE_STATUS_ATTEMPTS; attempt += 1) {
    const [runtimeResponse, workspaceResponse] = await Promise.all([
      api.get('/supervised-pilot/current-lever/runtime-control'),
      api.get('/supervised-pilot/current-lever'),
    ])
    lastRuntime = runtimeResponse.data
    lastWorkspace = workspaceResponse.data

    if (lastRuntime?.controller_available === false) {
      const pendingRequest = Boolean(lastRuntime?.pending_request)
      const inflightRequest = Boolean(lastRuntime?.inflight_request)
      const leaseActive = lastRuntime?.lease_active === true
      const executing = executingSubmissionCount(lastWorkspace)
      return {
        safe: !leaseActive && !pendingRequest && !inflightRequest && executing === 0,
        leaseActive,
        pendingRequest,
        inflightRequest,
        executingSubmissionCount: executing,
      }
    }

    await delay(QUIESCE_STATUS_INTERVAL_MS)
  }

  throw new Error(
    'Native pilot controller stopped, but the backend never confirmed its heartbeat was stale. Runtime update was not started.',
  )
}

export async function quiesceNativeRuntimeController() {
  requireNativeBootstrap()
  return NativeRuntimeBootstrap.quiesceController()
}

export async function restoreNativeRuntimeController() {
  requireNativeBootstrap()
  return NativeRuntimeBootstrap.restoreController()
}

export async function assertNoExecutingSubmissionsGlobally() {
  requireNativeBootstrap()
  return NativeRuntimeBootstrap.assertNoExecutingSubmissions()
}

export async function updateRuntimeViaLegacyNativeBootstrap() {
  requireNativeBootstrap()

  // This compatibility path is used only after the authenticated old backend has
  // explicitly returned 404/405 for the runtime-control endpoint. That proves this
  // runtime predates the signed pilot-controller/lease feature, so there is no native
  // controller to quiesce or lease state to read. We still fail closed on durable work:
  // the fixed PRoot guard queries every SubmissionAttempt and refuses the update if any
  // platform has queued or in-progress execution. No user-provided command is exposed.
  await assertNoExecutingSubmissionsGlobally()
  return NativeRuntimeBootstrap.updateRuntime()
}

export async function updateRuntimeViaNativeBootstrap() {
  requireNativeBootstrap()
  let controllerQuiesced = false

  try {
    await quiesceNativeRuntimeController()
    controllerQuiesced = true

    const safety = await readQuiescedSafetyState()
    if (!safety.safe) {
      throw new Error(
        'Native runtime bootstrap was aborted after quiescing the controller because fresh backend state showed an active lease, pending control request, inflight control request, or queued/in-progress Lever submission.',
      )
    }

    // The old backend does not expose a global SubmissionAttempt read endpoint.
    // Ask the existing PRoot runtime to query its own database directly through one
    // hard-coded native action. This is stricter than the Lever roster check and
    // fails closed if any platform has queued or in-progress work.
    await assertNoExecutingSubmissionsGlobally()

    const result = await NativeRuntimeBootstrap.updateRuntime()
    // The hardened `jobtomatik update` path completes with a managed restart that
    // starts the pilot controller again. Do not issue a second start on success.
    controllerQuiesced = false
    return result
  } catch (error) {
    if (controllerQuiesced) {
      try {
        await restoreNativeRuntimeController()
        controllerQuiesced = false
      } catch (restoreError) {
        const primary = error?.message || String(error)
        const restore = restoreError?.message || String(restoreError)
        throw new Error(`${primary} Pilot controller restore also failed: ${restore}`)
      }
    }
    throw error
  }
}