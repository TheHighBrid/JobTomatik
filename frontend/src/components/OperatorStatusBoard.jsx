import { useQuery } from '@tanstack/react-query'
import { getOperatorDiagnostics } from '../api/client'


function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900">{value}</span>
    </div>
  )
}


function Section({ title, rows }) {
  return (
    <>
      <h3 className="mt-4 text-xs uppercase tracking-wide text-gray-400">{title}</h3>
      <div className="mt-2 space-y-1">
        {rows.map(([label, value]) => (
          <Row key={label} label={label} value={value} />
        ))}
      </div>
    </>
  )
}


function ActionableErrors({ items }) {
  if (!items?.length) return null
  return (
    <ul className="mt-3 space-y-1 text-xs text-amber-700">
      {items.map((item) => <li key={item.code}>{item.action}</li>)}
    </ul>
  )
}


function downloadDiagnostics(report) {
  const payload = JSON.stringify(report, null, 2)
  const blob = new Blob([payload], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'jobtomatik-diagnostics.json'
  link.click()
  URL.revokeObjectURL(url)
}


function UnavailableBoard() {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4">
      <h2 className="text-lg font-bold tracking-wide">JOBTOMATIK</h2>
      <p className="mt-2 text-sm text-gray-500">Diagnostics unavailable.</p>
    </section>
  )
}


export default function OperatorStatusBoard() {
  const diagnostics = useQuery({
    queryKey: ['operatorDiagnostics'],
    queryFn: () => getOperatorDiagnostics().then((response) => response.data),
  })

  if (diagnostics.isLoading) return null
  if (diagnostics.isError || !diagnostics.data) return <UnavailableBoard />

  const report = diagnostics.data
  const statusRows = [
    ['OneHost', report.status.onehost],
    ['Worker', report.status.worker],
    ['Browser', report.status.browser],
    ['Database', report.status.database],
  ]
  const applicationRows = [
    ['Ready', report.applications.ready],
    ['Needs review', report.applications.needs_review],
    ['Applying', report.applications.applying],
    ['Confirmed', report.applications.confirmed],
  ]
  const safetyRows = [
    ['Autopilot', report.safety.autopilot],
    ['Real Submit', report.safety.real_submit],
    ['Kill Switch', report.safety.kill_switch],
  ]

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold tracking-wide">JOBTOMATIK</h2>
        <span className="text-xs text-gray-400">{report.version}</span>
      </div>

      <div className="mt-3">
        {statusRows.map(([label, value]) => (
          <Row key={label} label={label} value={value} />
        ))}
      </div>

      <Section title="Applications" rows={applicationRows} />
      <Section title="Safety" rows={safetyRows} />

      <p className="mt-3 text-xs text-gray-400">
        Handoffs open: {report.handoff.open}. Evidence available:{' '}
        {report.evidence.available ? 'yes' : 'no'}.
      </p>

      <ActionableErrors items={report.actionable_errors} />

      <button
        type="button"
        onClick={() => downloadDiagnostics(report)}
        className="mt-3 text-xs font-medium text-tomato-700"
      >
        Export diagnostics bundle
      </button>
    </section>
  )
}
