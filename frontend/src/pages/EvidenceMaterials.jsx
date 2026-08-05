import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  Clipboard,
  FileCheck2,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  XCircle,
} from 'lucide-react'
import api, {
  createEvidenceUnit,
  deactivateEvidenceUnit,
  generateApplicationMaterialBundle,
  getApiErrorMessage,
  listApplicationMaterials,
  listApplications,
  listEvidenceUnits,
  rebuildEvidenceLedger,
} from '../api/client'

const EMPTY_EVIDENCE = {
  kind: 'achievement',
  label: '',
  statement: '',
  organization: '',
  role: '',
}

function sourceLabel(unit) {
  if (unit.source_type === 'resume_pdf') return 'Résumé PDF'
  if (unit.source_type === 'career_memory') return 'Career memory'
  if (unit.source_type === 'manual') return 'Manual confirmation'
  return 'Profile'
}

function statusClasses(status) {
  if (status === 'verified' || status === 'approved') return 'bg-emerald-100 text-emerald-700'
  if (status === 'needs_review' || status === 'pending') return 'bg-amber-100 text-amber-800'
  if (status === 'rejected') return 'bg-red-100 text-red-800'
  return 'bg-slate-100 text-slate-700'
}

function EvidenceCard({ unit, onDeactivate, busy }) {
  return (
    <article className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
              {unit.kind.replaceAll('_', ' ')}
            </span>
            <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusClasses(unit.verification_status)}`}>
              {unit.verification_status.replaceAll('_', ' ')}
            </span>
          </div>
          <h3 className="mt-2 font-semibold text-gray-900">{unit.label}</h3>
          <p className="mt-1 text-sm leading-relaxed text-gray-700">{unit.statement}</p>
          {(unit.organization || unit.role) && (
            <p className="mt-2 text-xs text-gray-500">
              {[unit.role, unit.organization].filter(Boolean).join(' · ')}
            </p>
          )}
          <p className="mt-2 text-[11px] text-gray-400">
            {sourceLabel(unit)} · confidence {Math.round(Number(unit.confidence || 0) * 100)}%
          </p>
        </div>
        <button
          type="button"
          onClick={() => onDeactivate(unit.id)}
          disabled={busy}
          className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
          aria-label={`Deactivate ${unit.label}`}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </article>
  )
}

function MaterialCard({ material }) {
  const evidenceById = useMemo(
    () => new Map(
      (material.evidence_links || []).map((link) => [
        link.evidence_unit_id,
        link.evidence_unit,
      ]),
    ),
    [material.evidence_links],
  )
  const userReview = material.source_snapshot?.user_review || {}

  const copyMaterial = async () => {
    try {
      await navigator.clipboard.writeText(material.content)
      toast.success('Material copied.')
    } catch {
      toast.error('Copy failed on this device.')
    }
  }

  return (
    <article className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-5 py-4">
        <div>
          <div className="flex items-center gap-2">
            {material.material_type === 'cover_letter'
              ? <FileText className="h-5 w-5 text-tomato-600" />
              : <FileCheck2 className="h-5 w-5 text-tomato-600" />}
            <h3 className="font-semibold capitalize text-gray-900">
              {material.material_type.replaceAll('_', ' ')}
            </h3>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Version {material.version} · {material.generator_version}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(material.status)}`}>
            {material.status.replaceAll('_', ' ')}
          </span>
          {userReview.status && (
            <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(userReview.status)}`}>
              Owner review: {userReview.status.replaceAll('_', ' ')}
            </span>
          )}
          <button type="button" onClick={copyMaterial} className="btn-secondary inline-flex items-center gap-2 text-sm">
            <Clipboard className="h-4 w-4" /> Copy
          </button>
        </div>
      </div>

      <div className="space-y-5 p-5">
        {material.warnings?.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-center gap-2 font-semibold text-amber-900">
              <AlertTriangle className="h-4 w-4" /> Review warnings
            </div>
            <ul className="mt-2 space-y-1 text-sm text-amber-800">
              {material.warnings.map((warning) => <li key={warning}>• {warning}</li>)}
            </ul>
          </div>
        )}

        <pre className="whitespace-pre-wrap rounded-xl border border-gray-200 bg-gray-50 p-4 font-sans text-sm leading-relaxed text-gray-800">
          {material.content}
        </pre>

        <div>
          <h4 className="flex items-center gap-2 font-semibold text-gray-900">
            <ShieldCheck className="h-4 w-4 text-emerald-600" /> Claim audit
          </h4>
          <div className="mt-3 space-y-3">
            {(material.claims || []).map((claim, index) => {
              const evidence = (claim.evidence_unit_ids || [])
                .map((id) => evidenceById.get(id))
                .filter(Boolean)
              return (
                <div key={`${material.id}-${index}`} className="rounded-xl border border-gray-200 p-3">
                  <div className="flex items-start gap-2">
                    {claim.applicant_fact === false
                      ? <BookOpenCheck className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-600" />
                      : evidence.length
                        ? <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-600" />
                        : <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" />}
                    <div className="min-w-0">
                      <p className="text-sm text-gray-800">{claim.text}</p>
                      <p className="mt-1 text-[11px] uppercase tracking-wide text-gray-400">
                        {claim.category?.replaceAll('_', ' ')} · {claim.applicant_fact === false ? 'job/prose context' : `${evidence.length} evidence source${evidence.length === 1 ? '' : 's'}`}
                      </p>
                    </div>
                  </div>
                  {evidence.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {evidence.map((unit) => (
                        <span key={unit.id} className="rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700" title={unit.statement}>
                          #{unit.id} {unit.label}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </article>
  )
}

export default function EvidenceMaterials() {
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [form, setForm] = useState(EMPTY_EVIDENCE)
  const [kindFilter, setKindFilter] = useState('all')
  const [selectedApplicationId, setSelectedApplicationId] = useState('')
  const [reviewNotes, setReviewNotes] = useState('')
  const requestedApplicationId = searchParams.get('application') || ''

  const evidenceQuery = useQuery({
    queryKey: ['evidence-units'],
    queryFn: () => listEvidenceUnits(),
    select: (response) => response.data || [],
  })
  const applicationsQuery = useQuery({
    queryKey: ['applications-for-materials'],
    queryFn: () => listApplications({ per_page: 100 }),
    select: (response) => response.data || [],
  })
  const materialsQuery = useQuery({
    queryKey: ['application-materials', selectedApplicationId],
    queryFn: () => listApplicationMaterials(selectedApplicationId),
    select: (response) => response.data || [],
    enabled: Boolean(selectedApplicationId),
  })

  useEffect(() => {
    const applications = applicationsQuery.data || []
    if (!applications.length) return

    const requestedExists = applications.some(
      (application) => String(application.id) === String(requestedApplicationId),
    )
    const nextApplicationId = requestedExists
      ? String(requestedApplicationId)
      : String(applications[0].id)

    if (selectedApplicationId !== nextApplicationId) {
      setSelectedApplicationId(nextApplicationId)
    }
    if (requestedApplicationId !== nextApplicationId) {
      const nextParams = new URLSearchParams(searchParams)
      nextParams.set('application', nextApplicationId)
      setSearchParams(nextParams, { replace: true })
    }
  }, [
    applicationsQuery.data,
    requestedApplicationId,
    searchParams,
    selectedApplicationId,
    setSearchParams,
  ])

  const handleApplicationChange = (event) => {
    const nextApplicationId = event.target.value
    setSelectedApplicationId(nextApplicationId)
    setReviewNotes('')
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('application', nextApplicationId)
    setSearchParams(nextParams, { replace: true })
  }

  const rebuildMutation = useMutation({
    mutationFn: rebuildEvidenceLedger,
    onSuccess: (response) => {
      qc.invalidateQueries({ queryKey: ['evidence-units'] })
      const result = response.data
      toast.success(`Evidence refreshed: ${result.total_active} active units.`)
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Evidence refresh failed')),
  })

  const createMutation = useMutation({
    mutationFn: () => createEvidenceUnit({
      ...form,
      organization: form.organization || null,
      role: form.role || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['evidence-units'] })
      setForm(EMPTY_EVIDENCE)
      toast.success('Evidence confirmed and added.')
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Evidence could not be added')),
  })

  const deactivateMutation = useMutation({
    mutationFn: deactivateEvidenceUnit,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['evidence-units'] })
      toast.success('Evidence deactivated.')
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Evidence could not be deactivated')),
  })

  const bundleMutation = useMutation({
    mutationFn: () => generateApplicationMaterialBundle(selectedApplicationId),
    onSuccess: (response) => {
      qc.invalidateQueries({ queryKey: ['application-materials', selectedApplicationId] })
      qc.invalidateQueries({ queryKey: ['application', selectedApplicationId] })
      const materials = response.data?.materials || []
      if (materials.some((material) => material.status === 'needs_review')) {
        toast.error('Bundle generated, but evidence review is required before this application can advance.')
      } else {
        toast.success('Verified material bundle generated.')
      }
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Material generation failed')),
  })

  const evidence = evidenceQuery.data || []
  const kinds = ['all', ...new Set(evidence.map((unit) => unit.kind))]
  const filteredEvidence = kindFilter === 'all'
    ? evidence
    : evidence.filter((unit) => unit.kind === kindFilter)
  const selectedApplication = (applicationsQuery.data || []).find(
    (application) => String(application.id) === String(selectedApplicationId),
  )
  const retainedReviewId = selectedApplication?.application_target_metadata?.review_id || ''
  const retainedPlatform = selectedApplication?.application_target_metadata?.platform || ''
  const isRetainedLever = Boolean(retainedReviewId && retainedPlatform === 'lever')
  const latestMaterials = Object.values(
    (materialsQuery.data || []).reduce((accumulator, material) => {
      if (!accumulator[material.material_type]) accumulator[material.material_type] = material
      return accumulator
    }, {}),
  )
  const retainedBundle = ['cover_letter', 'resume_summary']
    .map((materialType) => latestMaterials.find((material) => material.material_type === materialType))
    .filter(Boolean)
  const retainedPreparation = retainedBundle.map(
    (material) => material.source_snapshot?.lever_phase_b_preparation || {},
  )
  const retainedReviewEligible = isRetainedLever
    && retainedBundle.length === 2
    && retainedPreparation.every(
      (snapshot) => snapshot.review_id === retainedReviewId && snapshot.review_eligible === true,
    )
  const retainedReviewApproved = retainedBundle.length === 2
    && retainedBundle.every(
      (material) => material.source_snapshot?.user_review?.status === 'approved',
    )

  const retainedPrepareMutation = useMutation({
    mutationFn: () => api.post(
      `/supervised-pilot/lever-launch/${encodeURIComponent(retainedReviewId)}/prepare-materials`,
    ),
    onSuccess: async (response) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['evidence-units'] }),
        qc.invalidateQueries({ queryKey: ['application-materials', selectedApplicationId] }),
        qc.invalidateQueries({ queryKey: ['application', selectedApplicationId] }),
        qc.invalidateQueries({ queryKey: ['applications-for-materials'] }),
        qc.invalidateQueries({ queryKey: ['lever-phase-b-launch'] }),
      ])
      if (response.data?.review_eligible) {
        toast.success('Retained Lever bundle prepared. Review both materials below.')
      } else {
        toast.error('The bundle has source-validation blockers that must be resolved.')
      }
    },
    onError: (error) => toast.error(
      getApiErrorMessage(error, 'Retained Lever material preparation failed'),
    ),
  })

  const retainedReviewMutation = useMutation({
    mutationFn: (approved) => api.post(
      `/supervised-pilot/lever-launch/${encodeURIComponent(retainedReviewId)}/review-materials`,
      {
        approved,
        notes: reviewNotes.trim() || null,
      },
    ),
    onSuccess: async (response) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['application-materials', selectedApplicationId] }),
        qc.invalidateQueries({ queryKey: ['application', selectedApplicationId] }),
        qc.invalidateQueries({ queryKey: ['applications-for-materials'] }),
        qc.invalidateQueries({ queryKey: ['lever-phase-b-launch'] }),
      ])
      setReviewNotes('')
      if (response.data?.ready_for_fresh_preflight) {
        toast.success('Material bundle approved. This application is ready for a fresh preflight.')
      } else if (response.data?.approved) {
        toast.error('Materials were approved, but another local review blocker remains.')
      } else {
        toast.success('Material bundle rejected and kept in review.')
      }
    },
    onError: (error) => toast.error(
      getApiErrorMessage(error, 'Material review could not be recorded'),
    ),
  })

  return (
    <div className="space-y-8 pb-24 md:pb-8">
      <header>
        <div className="flex items-center gap-2 text-tomato-600">
          <ShieldCheck className="h-5 w-5" />
          <span className="text-xs font-bold uppercase tracking-[0.18em]">Verified application intelligence</span>
        </div>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Evidence & Materials</h1>
        <p className="mt-1 max-w-3xl text-gray-500">
          Review the exact facts JobTomatik may use, then generate application materials where every applicant claim points back to a source.
        </p>
      </header>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,.75fr)]">
        <div className="space-y-4">
          <div className="card p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold text-gray-900">Evidence ledger</h2>
                <p className="mt-1 text-sm text-gray-500">
                  Profile fields, résumé text, career memories, and manual confirmations remain separate and traceable.
                </p>
              </div>
              <button
                type="button"
                onClick={() => rebuildMutation.mutate()}
                disabled={rebuildMutation.isPending}
                className="btn-secondary inline-flex items-center gap-2"
              >
                {rebuildMutation.isPending
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <RefreshCw className="h-4 w-4" />}
                Rebuild ledger
              </button>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {kinds.map((kind) => (
                <button
                  type="button"
                  key={kind}
                  onClick={() => setKindFilter(kind)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-semibold capitalize transition-colors ${
                    kindFilter === kind
                      ? 'border-tomato-600 bg-tomato-600 text-white'
                      : 'border-gray-200 bg-white text-gray-600 hover:border-tomato-300'
                  }`}
                >
                  {kind.replaceAll('_', ' ')}
                </button>
              ))}
            </div>
          </div>

          {evidenceQuery.isLoading ? (
            <div className="card flex items-center justify-center gap-2 p-10 text-gray-500">
              <Loader2 className="h-5 w-5 animate-spin" /> Loading evidence…
            </div>
          ) : filteredEvidence.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {filteredEvidence.map((unit) => (
                <EvidenceCard
                  key={unit.id}
                  unit={unit}
                  onDeactivate={(id) => deactivateMutation.mutate(id)}
                  busy={deactivateMutation.isPending}
                />
              ))}
            </div>
          ) : (
            <div className="card p-8 text-center text-gray-500">
              No active evidence units match this filter.
            </div>
          )}
        </div>

        <aside className="card h-fit p-5 xl:sticky xl:top-4">
          <div className="flex items-center gap-2">
            <Plus className="h-5 w-5 text-tomato-600" />
            <h2 className="font-semibold text-gray-900">Confirm a fact</h2>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Add only facts you are comfortable using in applications.
          </p>
          <div className="mt-5 space-y-4">
            <div>
              <label className="label">Evidence type</label>
              <select className="input" value={form.kind} onChange={(event) => setForm((value) => ({ ...value, kind: event.target.value }))}>
                {['achievement', 'employment', 'skill', 'education', 'credential', 'language', 'project', 'summary'].map((kind) => (
                  <option key={kind} value={kind}>{kind}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Label</label>
              <input className="input" value={form.label} onChange={(event) => setForm((value) => ({ ...value, label: event.target.value }))} placeholder="Case documentation" />
            </div>
            <div>
              <label className="label">Exact factual statement</label>
              <textarea className="input min-h-[120px] resize-y" value={form.statement} onChange={(event) => setForm((value) => ({ ...value, statement: event.target.value }))} placeholder="Maintained audit-ready case notes for fraud investigations." />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Organization</label>
                <input className="input" value={form.organization} onChange={(event) => setForm((value) => ({ ...value, organization: event.target.value }))} />
              </div>
              <div>
                <label className="label">Role</label>
                <input className="input" value={form.role} onChange={(event) => setForm((value) => ({ ...value, role: event.target.value }))} />
              </div>
            </div>
            <button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={!form.label.trim() || !form.statement.trim() || createMutation.isPending}
              className="btn-primary flex w-full items-center justify-center gap-2"
            >
              {createMutation.isPending
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : <CheckCircle2 className="h-4 w-4" />}
              Confirm evidence
            </button>
          </div>
        </aside>
      </section>

      <section className="space-y-4">
        <div className="card p-5">
          <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
            <div className="flex-1">
              <h2 className="font-semibold text-gray-900">Application materials</h2>
              <p className="mt-1 text-sm text-gray-500">
                Generate a cover letter and tailored résumé summary from the active ledger.
              </p>
              <label className="label mt-4">Application</label>
              <select
                className="input max-w-2xl"
                value={selectedApplicationId}
                onChange={handleApplicationChange}
              >
                {(applicationsQuery.data || []).map((application) => (
                  <option key={application.id} value={application.id}>
                    #{application.id} · {application.job?.title || 'Unknown role'} · {application.job?.company || 'Unknown company'}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              onClick={() => (
                isRetainedLever
                  ? retainedPrepareMutation.mutate()
                  : bundleMutation.mutate()
              )}
              disabled={
                !selectedApplicationId
                || bundleMutation.isPending
                || retainedPrepareMutation.isPending
              }
              className="btn-primary inline-flex items-center justify-center gap-2"
            >
              {(bundleMutation.isPending || retainedPrepareMutation.isPending)
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : isRetainedLever
                  ? <RefreshCw className="h-4 w-4" />
                  : <FileCheck2 className="h-4 w-4" />}
              {isRetainedLever ? 'Prepare official-source bundle' : 'Generate verified bundle'}
            </button>
          </div>
          {selectedApplication && (
            <p className="mt-3 text-xs text-gray-400">
              Current application state: {selectedApplication.automation_state?.replaceAll('_', ' ')}
              {isRetainedLever ? ` · retained candidate ${retainedReviewId}` : ''}
            </p>
          )}
          {isRetainedLever && (
            <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs leading-relaxed text-blue-900">
              This retained Lever workflow refreshes the exact public posting description before generation. Generic material generation is disabled for this candidate so stale or title-only context cannot be mistaken for a tailored bundle.
            </div>
          )}
        </div>

        {materialsQuery.isLoading && selectedApplicationId ? (
          <div className="card flex items-center justify-center gap-2 p-10 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" /> Loading materials…
          </div>
        ) : latestMaterials.length ? (
          <div className="grid gap-6 xl:grid-cols-2">
            {latestMaterials.map((material) => <MaterialCard key={material.id} material={material} />)}
          </div>
        ) : (
          <div className="card p-8 text-center text-gray-500">
            {applicationsQuery.data?.length
              ? 'No source-mapped materials exist for this application yet.'
              : 'Create an application before generating materials.'}
          </div>
        )}

        {isRetainedLever && retainedBundle.length > 0 && (
          <div className="card border border-blue-200 p-5">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-blue-700" />
              <div>
                <h3 className="font-semibold text-gray-900">Retained Lever material decision</h3>
                <p className="mt-1 text-sm leading-relaxed text-gray-600">
                  Approve only after reading both latest materials and checking the claim audit above. This decision approves the local text bundle only. It does not approve, queue, or submit an application.
                </p>
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {retainedBundle.map((material) => {
                const preparation = material.source_snapshot?.lever_phase_b_preparation || {}
                const review = material.source_snapshot?.user_review || {}
                return (
                  <div key={material.id} className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm">
                    <div className="font-semibold capitalize text-gray-900">
                      {material.material_type.replaceAll('_', ' ')} · v{material.version}
                    </div>
                    <div className="mt-1 text-xs text-gray-500">
                      Source validation: {preparation.review_eligible ? 'eligible' : 'blocked'} · owner review: {review.status || 'not recorded'}
                    </div>
                  </div>
                )
              })}
            </div>

            <label className="label mt-4">Review notes</label>
            <textarea
              className="input min-h-[90px] resize-y"
              value={reviewNotes}
              onChange={(event) => setReviewNotes(event.target.value)}
              placeholder="Record corrections, accepted warnings, or why the bundle is being rejected."
            />

            {!retainedReviewEligible && !retainedReviewApproved && (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
                Approval remains disabled because both latest materials are not source-valid for the same official posting and evidence snapshot. Refresh the bundle or correct the evidence first.
              </div>
            )}

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => retainedReviewMutation.mutate(false)}
                disabled={retainedReviewMutation.isPending || retainedBundle.length !== 2}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 bg-white px-4 py-2.5 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {retainedReviewMutation.isPending
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <XCircle className="h-4 w-4" />}
                Reject bundle
              </button>
              <button
                type="button"
                onClick={() => retainedReviewMutation.mutate(true)}
                disabled={
                  retainedReviewMutation.isPending
                  || !retainedReviewEligible
                  || retainedReviewApproved
                }
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {retainedReviewMutation.isPending
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <CheckCircle2 className="h-4 w-4" />}
                {retainedReviewApproved ? 'Bundle approved' : 'Approve reviewed bundle'}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
