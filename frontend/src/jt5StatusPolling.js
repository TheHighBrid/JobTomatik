export function jt5PollingInterval(response) {
  // Query state retains the Axios response; select only transforms observer data.
  const status = response?.data ?? response
  const attempt = status?.latest_attempt
  const active = ['queued', 'in_progress'].includes(attempt?.status)
    && attempt?.dispatch_status !== 'reconciliation_required'
  return active ? 1500 : false
}
