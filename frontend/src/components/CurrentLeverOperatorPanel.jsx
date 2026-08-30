import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileCheck2,
  Loader2,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import api, { getApiErrorMessage } from '../api/client'

function humanize(value) {
  return String(value || '').replaceAll('_', ' ')
}

function MaterialBlock({ title, material }) {
  if (!material) return null
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-slate-800">{title}</div>
        <div className="text-[10px] font-semibold text-emerald-700">
          {material.status || 'unknown'} · v{material.version || '—'}
        </div>
      </div>
      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-700">
        {material.content || 'No material content available.'}
      </pre>
      {material.warnings?.length > 0 && (
        <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-900">
          {material.warnings.join(' · ')}
        </div>
      )}
    </div>
  )
}

function CandidateCard({ candidate }) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [confirmingApproval, setConfirmingApproval] = useState(false)

  const applicationId = candidate.application_id
  const quarantined = (candidate.uncertain_submission_attempt_count || 0) > 0
  const eligible = candidate.material_preparation_eligible === true && !quarantined

  const materialsQuery = useQuery({
    queryKey: ['current-lever-materials', String(applicationId)],
    queryFn: () => api.get(`/supervised-pilot/current-lever/${applicationId}/materials`),
    select: (response) => response.data,
    enabled: expanded && !quarantined,
    retry: false,
  })

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['current-lever-workspace'] }),
      queryClient.invalidateQueries({ queryKey: ['current-lever-materials', String(applicationId)] }),
      queryClient.invalidateQueries({ queryKey: ['applications'] }),
      queryClient.invalidateQueries({ queryKey: ['appStats'] }),
    ])
  }

  const prepareMutation = useMutation({
    mutationFn: () => api.post(
      `/supervised-pilot/current-lever/${applicationId}/prepare-materials`,
    ),
    onSuccess: async () => {
      setExpanded(true)
      await refreshAll()
      toast.success('Current Lever materials prepared and ready for review.')
    },
    onError: (error) => toast.error(
      getApiErrorMessage(error, 'Could not prepare current Lever materials.'),
    ),
  })

  const reviewMutation = useMutation({
    mutationFn: ({ approved }) => api.post(
      `/supervised-pilot/current-lever/${applicationId}/review-materials`,
      approved
        ? {
            approved: true,
            acknowledgment: `APPROVE LEVER MATERIALS ${applicationId}`,
            notes: 'Reviewed in JobTomatik current Lever operator UI',
          }
        : {
            approved: false,
            notes: 'Rejected in JobTomatik current Lever operator UI',
          },
    ),
    onSuccess: async (response) => {
      setConfirmingApproval(false)
      await refreshAll()
      if (response.data?.approved === false) {
        toast.success('Material bundle rejected. Application remains blocked for revision.')
      } else {
        toast.success('Material bundle approved. Fresh runtime preflight is the next gate.')
      }
    },
    onError: (error) => toast.error(
      getApiErrorMessage(error, 'Could not record the material review decision.'),
    ),
  })

  const materials = materialsQuery.data?.materials
  const reviewEligible = materials
    && materials.cover_letter?.status === 'verified'
    && materials.resume_summary?.status === 'verified'
    && (materials.cover_letter?.warnings?.length || 0) === 0
    && (materials.resume_summary?.warnings?.length || 0) === 0

  return (
    <article className={`rounded-xl border p-4 ${
      quarantined
        ? 'border-red-200 bg-red-50'
        : 'border-slate-200 bg-white shadow-sm'
    }`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-950 px-2 py-0.5 text-[10px] font-semibold text-white">
              Application {applicationId}
            </span>
            <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
              quarantined
                ? 'border-red-200 bg-red-100 text-red-800'
                : eligible
                  ? 'border-emerald-200 bg-emerald-100 text-emerald-800'
                  : 'border-amber-200 bg-amber-100 text-amber-800'
            }`}>
              {quarantined ? 'Quarantined · no retry' : humanize(candidate.automation_state)}
            </span>
          </div>
          <h3 className="mt-2 text-sm font-semibold text-slate-950">{candidate.role}</h3>
          <p className="mt-0.5 text-xs text-slate-600">{candidate.employer}</p>
        </div>
        <a
          href={candidate.application_url}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-lg border border-slate-200 bg-white p-2 text-slate-500 hover:text-slate-900"
          aria-label={`Open ${candidate.employer} application`}
        >
          <ArrowUpRight className="h-4 w-4" />
        </a>
      </div>

      {quarantined ? (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-white p-3 text-xs leading-relaxed text-red-800">
          <LockKeyhole className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div>
            This application has {candidate.uncertain_submission_attempt_count} uncertain live submission attempt{candidate.uncertain_submission_attempt_count === 1 ? '' : 's'}. It is locked against preparation and retry until independent reconciliation evidence exists.
          </div>
        </div>
      ) : (
        <>
          {candidate.eligibility_blockers?.length > 0 && (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[11px] text-amber-900">
              {candidate.eligibility_blockers.map(humanize).join(' · ')}
            </div>
          )}

          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              disabled={!eligible || prepareMutation.isPending}
              onClick={() => prepareMutation.mutate()}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {prepareMutation.isPending
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : <RefreshCw className="h-3.5 w-3.5" />}
              Prepare / refresh materials
            </button>
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
            >
              <FileCheck2 className="h-3.5 w-3.5" />
              {expanded ? 'Hide material review' : 'Review materials'}
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>

          {expanded && (
            <div className="mt-4 space-y-3">
              {materialsQuery.isLoading && (
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading latest verified bundle…
                </div>
              )}

              {materialsQuery.isError && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                  {getApiErrorMessage(
                    materialsQuery.error,
                    'No current material bundle is available yet. Prepare it first.',
                  )}
                </div>
              )}

              {materials && (
                <>
                  <MaterialBlock title="Cover letter" material={materials.cover_letter} />
                  <MaterialBlock title="Résumé summary" material={materials.resume_summary} />

                  {candidate.automation_state === 'needs_review' && (
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                      <div className="flex items-start gap-2">
                        <ShieldCheck className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-700" />
                        <div>
                          <div className="text-xs font-semibold text-slate-900">Owner material decision</div>
                          <p className="mt-0.5 text-[11px] leading-relaxed text-slate-600">
                            Approval only accepts this exact application and latest verified bundle. It does not issue a submission approval, queue work, enable live flags, or click submit.
                          </p>
                        </div>
                      </div>

                      {confirmingApproval ? (
                        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                          <div className="text-xs font-semibold text-amber-900">
                            Approve materials for application {applicationId}?
                          </div>
                          <p className="mt-1 text-[11px] text-amber-800">
                            This records only the material review and advances to fresh runtime preflight.
                          </p>
                          <div className="mt-3 flex gap-2">
                            <button
                              type="button"
                              disabled={reviewMutation.isPending}
                              onClick={() => reviewMutation.mutate({ approved: true })}
                              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
                            >
                              {reviewMutation.isPending
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : <CheckCircle2 className="h-3.5 w-3.5" />}
                              Confirm material approval
                            </button>
                            <button
                              type="button"
                              disabled={reviewMutation.isPending}
                              onClick={() => setConfirmingApproval(false)}
                              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="mt-3 grid gap-2 sm:grid-cols-2">
                          <button
                            type="button"
                            disabled={!reviewEligible || reviewMutation.isPending}
                            onClick={() => setConfirmingApproval(true)}
                            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <CheckCircle2 className="h-3.5 w-3.5" /> Approve verified bundle
                          </button>
                          <button
                            type="button"
                            disabled={reviewMutation.isPending}
                            onClick={() => reviewMutation.mutate({ approved: false })}
                            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                          >
                            <XCircle className="h-3.5 w-3.5" /> Reject for revision
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {candidate.automation_state === 'ready_to_apply' && (
                    <Link
                      to={`/applications/${applicationId}`}
                      className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
                    >
                      <ShieldCheck className="h-3.5 w-3.5" /> Open fresh runtime preflight
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </Link>
                  )}
                </>
              )}
            </div>
          )}
        </>
      )}
    </article>
  )
}

export default function CurrentLeverOperatorPanel() {
  const workspaceQuery = useQuery({
    queryKey: ['current-lever-workspace'],
    queryFn: () => api.get('/supervised-pilot/current-lever'),
    select: (response) => response.data,
    retry: false,
    refetchInterval: 30000,
  })

  const candidates = useMemo(
    () => workspaceQuery.data?.candidates || [],
    [workspaceQuery.data],
  )

  if (workspaceQuery.isLoading) {
    return (
      <section className="card border border-slate-200 p-5">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading current Lever workspace…
        </div>
      </section>
    )
  }

  if (workspaceQuery.isError) {
    return (
      <section className="card border border-amber-200 bg-amber-50 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
          <AlertTriangle className="h-4 w-4" /> Current Lever workspace unavailable
        </div>
        <p className="mt-1 text-xs text-amber-800">
          {getApiErrorMessage(workspaceQuery.error, 'The current Lever workspace could not be loaded.')}
        </p>
      </section>
    )
  }

  return (
    <section className="card overflow-hidden border border-slate-200">
      <div className="border-b border-slate-200 bg-white px-5 py-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-700" />
              <h2 className="font-semibold text-slate-950">Current Lever operator</h2>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-600">
              The owner-selected supervised Lever workspace. Prepare, inspect, and review here. Terminal commands are not part of the normal workflow.
            </p>
          </div>
          <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">
            {workspaceQuery.data?.eligible_count || 0} eligible · {workspaceQuery.data?.candidate_count || 0} total
          </div>
        </div>
      </div>

      <div className="space-y-3 p-5">
        {candidates.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 p-5 text-center text-xs text-slate-500">
            No owner-selected current Lever target is in the workspace.
          </div>
        ) : (
          candidates.map((candidate) => (
            <CandidateCard key={candidate.application_id} candidate={candidate} />
          ))
        )}
      </div>
    </section>
  )
}
