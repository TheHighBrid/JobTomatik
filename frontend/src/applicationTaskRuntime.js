export const TERMINAL_TASK_STATUSES = new Set(['SUCCESS', 'FAILURE', 'REVOKED'])
export const TASK_START_ACK_TIMEOUT_MS = 45000

export function isApplicationTaskTerminal(status) {
  return TERMINAL_TASK_STATUSES.has(String(status || '').toUpperCase())
}

export function shouldReleaseUnacknowledgedTask({
  taskStatus,
  automationState,
  queuedAt,
  now = Date.now(),
  timeoutMs = TASK_START_ACK_TIMEOUT_MS,
}) {
  if (String(taskStatus || '').toUpperCase() !== 'PENDING') return false
  if (String(automationState || '').toLowerCase() === 'applying') return false
  if (!Number.isFinite(queuedAt) || queuedAt <= 0) return false
  return now - queuedAt >= timeoutMs
}

export function applicationRuntimeBusy({ submitting, taskId, automationState }) {
  return Boolean(
    submitting
    || taskId
    || String(automationState || '').toLowerCase() === 'applying'
  )
}
