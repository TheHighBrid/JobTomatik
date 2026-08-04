import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  ArrowUpRight,
  CheckCircle2,
  FilePlus2,
  Fingerprint,
  Loader2,
  LockKeyhole,
  ShieldCheck,
} from 'lucide-react'
import api, { getApiErrorMessage } from '../api/client'

function shortHash(value) {
  if (!value) return 'Unavailable'
  return `${value.slice(0, 10)}…${value.slice(-8)}`
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
              These two applications were selected by you and retained with exact dossier hashes. Adding one creates a preparation record only. It does not issue approval, open Lever, queue work, or submit.
            </p>
          </div>
          <div className="rounded-full border border-blue-300/30 bg-blue-300/10 px-3 py-1 text-xs font-semibold text-blue-100">
            {data.materialized_count} / {data.candidate_count} in workspace
          </div>
        </div>
      </div>

      <div className="space-y-4 p-5">
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
          The retained previews use a synthetic profile. Every materialized application still requires your real résumé, cover letter, approved answers, a fresh target preflight, and a separate short-lived approval before any supervised execution.
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          {data.candidates.map((candidate) => {
            const isPending = materialize.isPending
              && materialize.variables === candidate.review_id
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
                      {candidate.materialized && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                          <CheckCircle2 className="h-3 w-3" />
                          Added
                        </span>
                      )}
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
                  {candidate.materialized ? (
                    <Link
                      to={`/applications/${candidate.materialized_application_id}`}
                      className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
                    >
                      Open preparation record
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </Link>
                  ) : (
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
                  )}
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
          Materialization does not advance the campaign checkpoint. Day 16 counts only independently reviewed confirmation evidence from two distinct supervised submissions.
        </div>
      </div>
    </section>
  )
}
