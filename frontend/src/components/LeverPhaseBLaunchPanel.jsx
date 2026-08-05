import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ClipboardCheck,
  FileCheck2,
  FilePlus2,
  Fingerprint,
  Loader2,
  LockKeyhole,
  ShieldCheck,
} from 'lucide-react'
import api, { getApiErrorMessage } from '../api/client'

const STAGES = {
  not_materialized: {
    label: 'Not in workspace',
    description: 'Create the local preparation record before adding real materials.',
    badge: 'border-slate-200 bg-slate-100 text-slate-700',
  },
  verified_materials_required: {
    label: 'Verified materials required',
    description: 'Complete the real résumé, source-backed cover letter, and résumé summary.',
    badge: 'border-amber-200 bg-amber-100 text-amber-800',
  },
  review_required: {
    label: 'Review required',
    description: 'A material, review task, or application state must be resolved first.',
    badge: 'border-red-200 bg-red-100 text-red-800',
  },
  fresh_preflight_required: {
    label: 'Ready for fresh preflight',
    description: 'Local preparation is complete. The official target and exact real payload are not yet revalidated.',
    badge: 'border-blue-200 bg-blue-100 text-blue-800',
  },
  active_approval_present: {
    label: 'Active approval present',
    description: 'A short-lived Lever approval already exists. Review the exact approval state in the application.',
    badge: 'border-indigo-200 bg-indigo-100 text-indigo-800',
  },
  submission_state_present: {
    label: 'Submission state present',
    description: 'The local application has an attempt or later workflow state that requires inspection.',
    badge: 'border-emerald-200 bg-emerald-100 text-emerald-800',
  },
}

const BLOCKER_LABELS = {
  materialize_preparation_record: 'Preparation record not created',
  resume_required: 'Real résumé required',
  verified_cover_letter_required: 'Verified cover letter required',
  application_cover_letter_required: 'Verified cover letter not attached to application',
  verified_resume_summary_required: 'Verified résumé summary required',
  application_not_ready_to_apply: 'Application is not ready to apply',
  open_manual_review_tasks: 'Open manual review tasks',
  application_needs_review: 'Application is in needs-review state',
  cover_letter_review_required: 'Cover letter requires review',
  resume_summary_review_required: 'Résumé summary requires review',
}

function shortHash(value) {
  if (!value) return 'Unavailable'
  return `${value.slice(0, 10)}…${value.slice(-8)}`
}

function readable(value) {
  return BLOCKER_LABELS[value]
    || String(value || '').replaceAll('_', ' ')
}

function MaterialStatus({ label, status, version }) {
  const verified = status === 'verified'
  const review = status === 'needs_review'
  const text = status
    ? `${readable(status)}${version ? ` · v${version}` : ''}`
    : 'Not generated'
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px]">
      <span className="font-medium text-slate-600">{label}</span>
      <span className={verified ? 'font-semibold text-emerald-700' : review ? 'font-semibold text-red-700' : 'font-semibold text-slate-500'}>
        {text}
      </span>
    </div>
  )
}

function CandidateAction({ candidate, materialize, isPending }) {
  if (candidate.preparation_next_action === 'materialize') {
    return (
      <button
        type="button"
        onClick={() => materialize.mutate(candidate.review_id)}
        disabled={materialize.isPending}
        className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isPending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <FilePlus2 className="h-3.5 w-3.5" />
        )}
        Add preparation record
      </button>
    )
  }

  const applicationId = candidate.materialized_application_id
  const actions = {
    build_verified_materials: {
      to: `/evidence-materials?application=${applicationId}`,
      label: 'Build verified materials',
      icon: FileCheck2,
    },
    resolve_review: {
      to: `/applications/${applicationId}`,
      label: 'Resolve review',
      icon: AlertTriangle,
    },
    open_fresh_preflight: {
      to: `/applications/${applicationId}`,
      label: 'Open fresh preflight',
      icon: ClipboardCheck,
    },
    review_active_approval: {
      to: `/applications/${applicationId}`,
      label: 'Review active approval',
      icon: LockKeyhole,
    },
    inspect_submission_state: {
      to: `/applications/${applicationId}`,
      label: 'Inspect submission state',
      icon: CheckCircle2,
    },
  }
  const action = actions[candidate.preparation_next_action] || actions.open_fresh_preflight
  const Icon = action.icon
  return (
    <Link
      to={action.to}
      className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
    >
      <Icon className="h-3.5 w-3.5" />
      {action.label}
      <ArrowUpRight className="h-3.5 w-3.5" />
    </Link>
  )
}

export default function LeverPhaseBLaunchPanel() {
  const queryClient = useQueryClient()
  const launchQuery = useQuery({
    queryKey: ['lever-phase-b-launch'],
    queryFn: () => api.get('/supervised-pilot/lever-launch'),
    select: (response) => response.data,
    retry: false,
  })
  const materialize = useMutation({
    mutationFn: (reviewId) => api.post(
      `/supervised-pilot/lever-launch/${encodeURIComponent(reviewId)}/materialize`,
    ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['lever-phase-b-launch'] }),
        queryClient.invalidateQueries({ queryKey: ['applications'] }),
        queryClient.invalidateQueries({ queryKey: ['appStats'] }),
        queryClient.invalidateQueries({ queryKey: ['supervised-pilot-roster'] }),
      ])
    },
  })

  if (launchQuery.isLoading) {
    return (
      <section className="card border border-blue-200 p-5">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Verifying retained Lever launch dossiers…
        </div>
      </section>
    )
  }

  if (launchQuery.isError || !launchQuery.data) {
    return (
      <section className="card border border-amber-200 bg-amber-50 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
          <LockKeyhole className="h-4 w-4" />
          Lever launch evidence is unavailable
        </div>
        <p className="mt-1 text-xs leading-relaxed text-amber-800">
          {getApiErrorMessage(
            launchQuery.error,
            'The retained dossiers could not be verified. No preparation record was created.',
          )}
        </p>
      </section>
    )
  }

  const data = launchQuery.data

  return (
    <section className="card overflow-hidden border border-blue-200">
      <div className="border-b border-blue-200 bg-slate-950 px-5 py-4 text-white">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-blue-300" />
              <h2 className="font-semibold">Lever Day 16 launch candidates</h2>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-300">
              Each stage is derived from your local JobTomatik records. This overview never contacts Lever, issues approval, queues work, or submits.
            </p>
          </div>
          <div className="rounded-full border border-blue-300/30 bg-blue-300/10 px-3 py-1 text-xs font-semibold text-blue-100">
            {data.materialized_count} / {data.candidate_count} in workspace
          </div>
        </div>
      </div>

      <div className="space-y-4 p-5">
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
          The retained previews use a synthetic profile. “Ready for fresh preflight” means local preparation is complete only. It does not mean the current Lever posting, exact payload, execution flags, or final-submit boundary have passed.
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          {data.candidates.map((candidate) => {
            const isPending = materialize.isPending
              && materialize.variables === candidate.review_id
            const stage = STAGES[candidate.preparation_stage] || STAGES.not_materialized
            return (
              <article
                key={candidate.review_id}
                className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-800">
                        {candidate.review_id}
                      </span>
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${stage.badge}`}>
                        {stage.label}
                      </span>
                    </div>
                    <h3 className="mt-2 text-sm font-semibold text-slate-950">
                      {candidate.role}
                    </h3>
                    <p className="mt-0.5 text-xs text-slate-600">
                      {candidate.employer}
                      {candidate.location ? ` · ${candidate.location}` : ''}
                    </p>
                  </div>
                  <a
                    href={candidate.application_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 hover:text-slate-800"
                    aria-label={`Open ${candidate.employer} Lever posting`}
                  >
                    <ArrowUpRight className="h-4 w-4" />
                  </a>
                </div>

                <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-start gap-2">
                    <ClipboardCheck className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-500" />
                    <p className="text-xs leading-relaxed text-slate-700">{stage.description}</p>
                  </div>
                  {candidate.preparation_blockers?.length > 0 && (
                    <ul className="mt-2 space-y-1 text-[11px] text-slate-600">
                      {candidate.preparation_blockers.map((blocker) => (
                        <li key={blocker} className="flex items-start gap-1.5">
                          <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-amber-500" />
                          {readable(blocker)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {candidate.materialized && (
                  <div className="mt-3 space-y-2">
                    <MaterialStatus
                      label="Cover letter"
                      status={candidate.cover_letter_material_status}
                      version={candidate.cover_letter_material_version}
                    />
                    <MaterialStatus
                      label="Résumé summary"
                      status={candidate.resume_summary_material_status}
                      version={candidate.resume_summary_material_version}
                    />
                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      <div className="rounded-lg border border-slate-200 px-3 py-2 text-slate-600">
                        Résumé: <strong className={candidate.resume_present ? 'text-emerald-700' : 'text-amber-700'}>
                          {candidate.resume_present ? 'Present' : 'Missing'}
                        </strong>
                      </div>
                      <div className="rounded-lg border border-slate-200 px-3 py-2 text-slate-600">
                        Open reviews: <strong className={candidate.open_review_count ? 'text-red-700' : 'text-emerald-700'}>
                          {candidate.open_review_count || 0}
                        </strong>
                      </div>
                    </div>
                  </div>
                )}

                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
                    <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                      <Fingerprint className="h-3 w-3" /> Dossier
                    </div>
                    <code className="mt-1 block text-[10px] text-slate-700" title={candidate.dossier_sha256}>
                      {shortHash(candidate.dossier_sha256)}
                    </code>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
                    <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                      <Fingerprint className="h-3 w-3" /> Phase A source
                    </div>
                    <code className="mt-1 block text-[10px] text-slate-700" title={candidate.source_report_sha256}>
                      {shortHash(candidate.source_report_sha256)}
                    </code>
                  </div>
                </div>

                <div className="mt-3">
                  <CandidateAction
                    candidate={candidate}
                    materialize={materialize}
                    isPending={isPending}
                  />
                </div>
              </article>
            )
          })}
        </div>

        {materialize.isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-800">
            {getApiErrorMessage(
              materialize.error,
              'The retained candidate could not be materialized.',
            )}
          </div>
        )}

        <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          Preparation stages do not advance the campaign checkpoint. Day 16 counts only independently reviewed confirmation evidence from two distinct supervised submissions.
        </div>
      </div>
    </section>
  )
}
