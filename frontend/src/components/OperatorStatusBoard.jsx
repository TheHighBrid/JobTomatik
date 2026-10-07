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

export default function OperatorStatusBoard() {
  const diagnostics = useQuery({
    queryKey: ['operatorDiagnostics'],
    queryFn: () => getOperatorDiagnostics().then((response) => response.data),
  })
  const report = diagnostics.data
  if (!report) return null
  const download = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'jobtomatik-diagnostics.json'
    link.click()
    URL.revokeObjectURL(url)
  }
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold tracking-wide">JOBTOMATIK</h2>
        <span className="text-xs text-gray-400">{report.version}</span>
      </div>
      <div className="mt-3 space-y-1">
        <Row label="OneHost" value={report.status.onehost} />
        <Row label="Worker" value={report.status.worker} />
        <Row label="Browser" value={report.status.browser} />
        <Row label="Database" value={report.status.database} />
      </div>
      <h3 className="mt-4 text-xs uppercase tracking-wide text-gray-400">Applications</h3>
      <div className="mt-2 space-y-1">
        <Row label="Ready" value={report.applications.ready} />
        <Row label="Needs review" value={report.applications.needs_review} />
        <Row label="Applying" value={report.applications.applying} />
        <Row label="Confirmed" value={report.applications.confirmed} />
      </div>
      <h3 className="mt-4 text-xs uppercase tracking-wide text-gray-400">Safety</h3>
      <div className="mt-2 space-y-1">
        <Row label="Autopilot" value={report.safety.autopilot} />
        <Row label="Real Submit" value={report.safety.real_submit} />
        <Row label="Kill Switch" value={report.safety.kill_switch} />
      </div>
      <p className="mt-3 text-xs text-gray-400">Handoffs open: {report.handoff.open}. Evidence available: {report.evidence.available ? 'yes' : 'no'}.</p>
      {report.actionable_errors?.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-amber-700">
          {report.actionable_errors.map((item) => <li key={item.code}>{item.action}</li>)}
        </ul>
      )}
      <button type="button" onClick={download} className="mt-3 text-xs font-medium text-tomato-700">
        Export diagnostics bundle
      </button>
    </section>
  )
}
