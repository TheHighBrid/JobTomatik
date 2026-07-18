import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  FileKey2,
  Flag,
  Loader2,
  LockKeyhole,
  Plus,
  ShieldCheck,
  X,
} from 'lucide-react'
import api from '../api/client'
import SupervisedPilotDossierPanel from './SupervisedPilotDossierPanel'

function label(value) {
  return String(value || '').replaceAll('_', ' ')
}

function Progress({ name, value, target }) {
  const bounded = Math.min(target, Math.max(0, Number(value || 0)))
  const width = target ? `${Math.round((bounded / target) * 100)}%` : '0%'
  return (
    <div className="rounded-lg border border-indigo-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium text-slate-700">{name}</span>
        <strong className="text-indigo-950">{value || 0} / {target}</strong>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-indigo-100">
        <div className="h-full rounded-full bg-indigo-600" style={{ width }} />
      </div>
    </div>
  )
}

function StatusIcon({ status }) {
  if (status === 'recorded_in_pilot_ledger') return <CheckCircle2 className="h-4 w-4 text-emerald-600" />
  if (status === 'confirmed_pending_ledger_ingestion') return <ClipboardCheck className="h-4 w-4 text-indigo-600" />
  if (status === 'available_for_user_review') return <ShieldCheck className="h-4 w-4 text-blue-600" />
  return <AlertTriangle className="h-4 w-4 text-amber-600" />
}

const EMPTY_INTAKE = {
  employer: '',
  role: '',
  application_url: '',
  location: '',
}

export default function SupervisedPilotRoster() {
  const queryClient = useQueryClient()
  const [selectedDossierId, setSelectedDossierId] = useState(null)
  const [intake, setIntake] = useState(EMPTY_INTAKE)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['supervised-pilot-roster'],
    queryFn: () => api.get('/supervised-pilot/roster'),
    select: (response) => response.data,
    retry: false,
  })
  const importCandidate = useMutation({
    mutationFn: (payload) => api.post('/supervised-pilot/candidates', payload),
    onSuccess: async (response) => {
      setIntake(EMPTY_INTAKE)
      setSelectedDossierId(response.data.application_id)
      await queryClient.invalidateQueries({ queryKey: ['supervised-pilot-roster'] })
    },
  })

  const updateIntake = (field, value) => {
    setIntake((current) => ({ ...current, [field]: value }))
  }

  const submitIntake = (event) => {
    event.preventDefault()
    importCandidate.mutate({
      employer: intake.employer,
      role: intake.role,
      application_url: intake.application_url,
      location: intake.location || null,
      source_reference: 'phase-b-roster-operator-intake',
    })
  }

  if (isLoading) {
    return (
      <section className="card p-5">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading supervised pilot roster…
        </div>
      </section>
    )
  }

  if (isError || !data) {
    return (
      <section className="card border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
        The supervised pilot roster is unavailable. No application was selected or queued.
      </section>
    )
  }

  return (
    <section className="card overflow-hidden border border-indigo-200">
      <div className="border-b border-indigo-200 bg-indigo-950 px-5 py-4 text-white">
        <div className="flex items-center gap-2">
          <Flag className="h-5 w-5" />
          <h2 className="font-semibold">Greenhouse supervised pilot roster</h2>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-indigo-200">
          Technical readiness only. Applications are shown in creation order, never ranked or selected automatically. Open an exact dossier before using the separate approval panel.
        </p>
      </div>

      <div className="space-y-4 p-5">
        <div className="grid gap-2 md:grid-cols-3">
          <Progress name="Dry runs" value={data.phase_a.qualifying_dry_run_count} target={30} />
          <Progress name="Distinct employers" value={data.phase_a.distinct_employer_count} target={30} />
          <Progress name="Confirmed pilot records" value={data.phase_b.confirmed_count} target={data.phase_b.target} />
        </div>

        <div className="grid gap-2 md:grid-cols-2">
          <div className={`rounded-lg border p-3 text-xs ${data.execution_flags.global_live_submit_enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
            <div className="flex items-center gap-2 font-semibold">
              <LockKeyhole className="h-4 w-4" /> Global live-submit flag
            </div>
            <div className="mt-1">{data.execution_flags.global_live_submit_enabled ? 'Enabled' : 'Disabled'}</div>
          </div>
          <div className={`rounded-lg border p-3 text-xs ${data.execution_flags.greenhouse_supervised_pilot_enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
            <div className="flex items-center gap-2 font-semibold">
              <LockKeyhole className="h-4 w-4" /> Greenhouse pilot flag
            </div>
            <div className="mt-1">{data.execution_flags.greenhouse_supervised_pilot_enabled ? 'Enabled' : 'Disabled'}</div>
          </div>
        </div>

        <form onSubmit={submitIntake} className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <div className="flex items-start gap-2">
            <Plus className="mt-0.5 h-4 w-4 text-blue-700" />
            <div>
              <h3 className="text-sm font-semibold text-blue-950">Import one exact Greenhouse candidate</h3>
              <p className="mt-0.5 text-xs leading-relaxed text-blue-800">
                This creates a preparation record only. It does not enable flags, issue an approval, open a browser, or queue a submission.
              </p>
            </div>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <input
              required
              value={intake.employer}
              onChange={(event) => updateIntake('employer', event.target.value)}
              placeholder="Exact employer"
              className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs text-slate-900 outline-none focus:border-blue-500"
            />
            <input
              required
              value={intake.role}
              onChange={(event) => updateIntake('role', event.target.value)}
              placeholder="Exact role"
              className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs text-slate-900 outline-none focus:border-blue-500"
            />
            <input
              required
              type="url"
              value={intake.application_url}
              onChange={(event) => updateIntake('application_url', event.target.value)}
              placeholder="https://job-boards.greenhouse.io/company/jobs/123"
              className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs text-slate-900 outline-none focus:border-blue-500 md:col-span-2"
            />
            <input
              value={intake.location}
              onChange={(event) => updateIntake('location', event.target.value)}
              placeholder="Location, optional"
              className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs text-slate-900 outline-none focus:border-blue-500"
            />
            <button
              type="submit"
              disabled={importCandidate.isPending}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {importCandidate.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              Add to preparation roster
            </button>
          </div>
          {importCandidate.isError && (
            <div className="mt-2 text-xs font-medium text-red-700">
              {importCandidate.error?.response?.data?.detail || 'The candidate could not be imported.'}
            </div>
          )}
          {importCandidate.isSuccess && (
            <div className="mt-2 text-xs font-medium text-emerald-700">
              Candidate staged safely. Review its dossier before any separate approval action.
            </div>
          )}
        </form>

        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600">
          <span>{data.candidate_count} Greenhouse application(s) · {data.technically_ready_count} structurally ready</span>
          <span>{data.phase_b.remaining} independently confirmed record(s) remaining</span>
        </div>

        {data.candidates.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 p-5 text-center text-sm text-slate-500">
            No Greenhouse applications are currently available. Nothing was selected automatically.
          </div>
        ) : (
          <div className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
            {data.candidates.map((candidate) => (
              <div key={candidate.application_id} className="p-4">
                <div className="flex items-start gap-3">
                  <StatusIcon status={candidate.roster_status} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong className="text-sm text-slate-900">{candidate.role}</strong>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium capitalize text-slate-600">
                        {label(candidate.roster_status)}
                      </span>
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">{candidate.employer}</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {candidate.technical_blockers.map((blocker) => (
                        <span key={blocker} className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800">
                          {label(blocker)}
                        </span>
                      ))}
                      {candidate.technical_ready && (
                        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-800">
                          technical preflight clear
                        </span>
                      )}
                      {candidate.active_approval_reference && (
                        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-medium text-indigo-800">
                          active one-time approval
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => setSelectedDossierId((current) => (
                        current === candidate.application_id ? null : candidate.application_id
                      ))}
                      className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 px-2.5 py-1.5 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-50"
                    >
                      {selectedDossierId === candidate.application_id
                        ? <X className="h-3.5 w-3.5" />
                        : <FileKey2 className="h-3.5 w-3.5" />}
                      {selectedDossierId === candidate.application_id ? 'Close dossier' : 'Review dossier'}
                    </button>
                    <Link
                      to={`/applications/${candidate.application_id}`}
                      className="rounded-lg p-2 text-slate-400 hover:bg-slate-50 hover:text-slate-700"
                      aria-label={`Open ${candidate.role} application`}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Link>
                  </div>
                </div>

                {selectedDossierId === candidate.application_id && (
                  <div className="mt-4">
                    <SupervisedPilotDossierPanel applicationId={candidate.application_id} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          The roster, intake, and dossier do not judge job suitability. Sensitive answers are not shown, and each application still requires exact employer, role, URL, payload, and final-action confirmation in its supervised panel.
        </div>
      </div>
    </section>
  )
}
