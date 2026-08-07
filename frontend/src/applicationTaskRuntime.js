export const APPLICATION_TASK_RUNTIME_PROTOCOL = 'android-task-runtime-v2'
export const TERMINAL_TASK_STATUSES = new Set(['SUCCESS', 'FAILURE', 'REVOKED'])
export const TASK_START_ACK_TIMEOUT_MS = 45000

export function isApplicationTaskTerminal(status) {
  return TERMINAL_TASK_STATUSES.has(String(status || '').toUpperCase())
}

export function shouldReleaseUnacknowledgedTask({
  taskStatus,
  automationState: _automationState,
  queuedAt,
  now = Date.now(),
  timeoutMs = TASK_START_ACK_TIMEOUT_MS,
}) {
  if (String(taskStatus || '').toUpperCase() !== 'PENDING') return false
  if (!Number.isFinite(queuedAt) || queuedAt <= 0) return false

  // A real worker-owned task must become STARTED (task_track_started=true) on the
  // same result backend that accepted the dispatch. Treating a database row that
  // merely says `applying` as stronger evidence allowed orphaned or cross-broker
  // attempts to pin the UI forever. PENDING beyond the acknowledgement budget is
  // therefore always a lost/unacknowledged task from the browser's perspective.
  return now - queuedAt >= timeoutMs
}

export function applicationRuntimeBusy({ submitting, taskId, automationState }) {
  return Boolean(
    submitting
    || taskId
    || String(automationState || '').toLowerCase() === 'applying'
  )
}
