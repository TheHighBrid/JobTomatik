import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileKey2,
  Fingerprint,
  Loader2,
  LockKeyhole,
  ShieldCheck,
} from 'lucide-react'
import api from '../api/client'

function label(value) {
  return String(value || '').replaceAll('_', ' ')
}

function shortHash(value) {
  const text = String(value || '')
  if (!text) return 'not available'
  return `${text.slice(0, 12)}…${text.slice(-8)}`
}

function Gate({ ok, children }) {
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
      ok
        ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
        : 'border-amber-200 bg-amber-50 text-amber-800'
    }`}>
      {ok
        ? <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
        : <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />}
      <span>{children}</span>
    </div>
  )
}

export default function SupervisedPilotDossierPanel({ applicationId, enabled = true }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['supervised-pilot-dossier', applicationId],
    queryFn: () => api.get(`/supervised-pilot/applications/${applicationId}/dossier`),
    select: (response) => response.data,
    enabled: Boolean(enabled && applicationId),
    retry: false,
  })

  if (!enabled) return null

  if (isLoading) {
    return (
      <section className="card border border-indigo-200 p-5">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Building sanitized Phase B dossier…
        </div>
      </section>
    )
  }

  if (isError || !data) {
    return (
      <section className="card border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
        The Phase B dossier is unavailable. No approval was issued and no submission was queued.
      </section>
    )
  }

  const downloadDossier = () => {
    const blob = new Blob([`${JSON.stringify(data, null, 2)}\n`], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = data.download_filename
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const structuralReady = data.preflight.technical_ready
  const payloadComplete = Boolean(
    data.exact_payload.resume_hash
    && data.exact_payload.combined_payload_hash
    && data.application_state.duplicate_prevention_key_present
  )

  return (
    <section className="card overflow-hidden border border-indigo-200">
      <div className="border-b border-indigo-200 bg-indigo-950 px-5 py-4 text-white">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <FileKey2 className="h-5 w-5" />
              <h2 className="font-semibold">Phase B candidate dossier</h2>
            </div>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-indigo-200">
              One deterministic, sanitized snapshot for this exact application. It contains hashes and safety state, never raw profile answers, and exposes no approval or submit action.
            </p>
          </div>
          <button
            type="button"
            onClick={downloadDossier}
            className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-400 bg-indigo-900 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-800"
          >
            <Download className="h-4 w-4" /> Download JSON
          </button>
        </div>
      </div>

      <div className="space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Exact target</div>
            <div className="mt-1 text-sm font-semibold text-slate-900">{data.target.role}</div>
            <div className="text-xs text-slate-500">{data.target.employer}</div>
            <div className="mt-2 break-all text-[11px] text-slate-500">{data.target.application_url}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              <Fingerprint className="h-3.5 w-3.5" /> Dossier digest
            </div>
            <code className="mt-2 block break-all text-[11px] text-slate-700">{data.dossier_sha256}</code>
            <div className="mt-2 text-[11px] text-slate-500">
              Re-fetch before approval. A changed digest means the payload or retained evidence changed.
            </div>
          </div>
        </div>

        <div className="grid gap-2 md:grid-cols-2">
          <Gate ok={data.pilot_progress.phase_a_complete}>
            Phase A baseline: {data.pilot_progress.phase_a_qualifying_dry_runs} dry runs across {data.pilot_progress.phase_a_distinct_employers} employers
          </Gate>
          <Gate ok={structuralReady}>
            {structuralReady ? 'Technical preflight is clear' : `${data.preflight.structural_blockers.length} structural blocker(s) remain`}
          </Gate>
          <Gate ok={payloadComplete}>
            Exact résumé, answer-policy, cover-letter, and duplicate-prevention hashes are present
          </Gate>
          <Gate ok={!data.kill_switches.global_flag_enabled && !data.kill_switches.platform_flag_enabled}>
            Both live-execution flags remain disabled in this snapshot
          </Gate>
        </div>

        {(data.preflight.structural_blockers.length > 0 || data.preflight.execution_blockers.length > 0) && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-amber-900">
              <LockKeyhole className="h-4 w-4" /> Current blockers
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {data.preflight.execution_blockers.map((blocker) => (
                <span key={blocker} className="rounded-full bg-white px-2 py-0.5 text-[10px] font-medium text-amber-800 ring-1 ring-amber-200">
                  {label(blocker)}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-slate-200 p-3 text-xs text-slate-600">
            <div className="flex items-center gap-2 font-semibold text-slate-800">
              <ShieldCheck className="h-4 w-4" /> Exact payload hashes
            </div>
            <dl className="mt-2 space-y-1.5">
              <div className="flex justify-between gap-3"><dt>Combined</dt><dd className="font-mono">{shortHash(data.exact_payload.combined_payload_hash)}</dd></div>
              <div className="flex justify-between gap-3"><dt>Résumé</dt><dd className="font-mono">{shortHash(data.exact_payload.resume_hash)}</dd></div>
              <div className="flex justify-between gap-3"><dt>Cover letter</dt><dd className="font-mono">{shortHash(data.exact_payload.cover_letter_hash)}</dd></div>
              <div className="flex justify-between gap-3"><dt>Answers</dt><dd className="font-mono">{shortHash(data.exact_payload.answer_payload_hash)}</dd></div>
            </dl>
          </div>
          <div className="rounded-lg border border-slate-200 p-3 text-xs text-slate-600">
            <div className="font-semibold text-slate-800">Evidence and review state</div>
            <dl className="mt-2 space-y-1.5">
              <div className="flex justify-between"><dt>Submission attempts</dt><dd>{data.application_state.submission_attempt_count}</dd></div>
              <div className="flex justify-between"><dt>Sufficient evidence</dt><dd>{data.submission_evidence_state.sufficient_count}</dd></div>
              <div className="flex justify-between"><dt>Accepted independent reviews</dt><dd>{data.independent_review_state.accepted_count}</dd></div>
              <div className="flex justify-between"><dt>Pilot records remaining</dt><dd>{data.pilot_progress.phase_b_remaining}</dd></div>
            </dl>
          </div>
        </div>

        <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          Mandatory stops remain in force for CAPTCHA, anti-bot checks, MFA, login, assessments, identity verification, and ambiguous legal or consent boundaries. The dossier cannot bypass, approve, or submit.
        </div>
      </div>
    </section>
  )
}
