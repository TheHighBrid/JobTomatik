import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Download,
  ExternalLink,
  FileCheck2,
  Fingerprint,
  Loader2,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import {
  createSubmissionEvidenceReview,
  exportSupervisedPilotRecord,
  getSubmissionEvidenceReviewPreflight,
  listSubmissionEvidence,
  listSubmissionEvidenceReviews,
} from '../api/client'

function compactHash(value) {
  if (!value) return 'Not available'
  return `${String(value).slice(0, 14)}…${String(value).slice(-10)}`
}

function formatDate(value) {
  if (!value) return 'Unknown time'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function blockerLabel(value) {
  return String(value || '').replaceAll('_', ' ')
}

function EvidenceSummary({ evidence }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-600">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold text-slate-900">{evidence.evidence_type}</span>
        <span className={`rounded-full px-2 py-0.5 font-medium ${evidence.is_sufficient ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
          {evidence.is_sufficient ? 'Adapter marked sufficient' : 'Not sufficient'}
        </span>
      </div>
      <div className="mt-2 grid gap-1 md:grid-cols-2">
        <span>Captured: {formatDate(evidence.captured_at)}</span>
        <span>Evidence ID: {evidence.id}</span>
        <span>External ID: {evidence.external_application_id ? 'Present' : 'Not present'}</span>
        <span>Screenshot: {evidence.screenshot_path ? 'Present' : 'Not present'}</span>
        <span>HTML snapshot: {evidence.html_snapshot_path ? 'Present' : 'Not present'}</span>
        <span>Payload hash: {compactHash(evidence.payload_hash)}</span>
      </div>
      {evidence.final_url && (
        <a
          href={evidence.final_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-tomato-600 hover:underline"
        >
          Open retained final URL <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </div>
  )
}

export default function SubmissionEvidenceReviewPanel({ application }) {
  const applicationId = Number(application?.id)
  const qc = useQueryClient()
  const [selectedEvidenceId, setSelectedEvidenceId] = useState(null)
  const [decision, setDecision] = useState('accepted')
  const [confirmEmployer, setConfirmEmployer] = useState('')
  const [confirmRole, setConfirmRole] = useState('')
  const [confirmEvidenceType, setConfirmEvidenceType] = useState('')
  const [matchesApplication, setMatchesApplication] = useState(false)
  const [acknowledgement, setAcknowledgement] = useState('')
  const [notes, setNotes] = useState('')

  const evidenceQuery = useQuery({
    queryKey: ['submission-evidence', applicationId],
    queryFn: () => listSubmissionEvidence(applicationId),
    select: (response) => response.data || [],
    enabled: Boolean(applicationId),
  })

  const reviewsQuery = useQuery({
    queryKey: ['submission-evidence-reviews', applicationId],
    queryFn: () => listSubmissionEvidenceReviews(applicationId),
    select: (response) => response.data || [],
    enabled: Boolean(applicationId),
  })

  const evidence = evidenceQuery.data || []
  const selectedEvidence = useMemo(
    () => evidence.find((item) => item.id === selectedEvidenceId) || null,
    [evidence, selectedEvidenceId],
  )

  useEffect(() => {
    if (!selectedEvidenceId && evidence.length) setSelectedEvidenceId(evidence[0].id)
  }, [evidence, selectedEvidenceId])

  useEffect(() => {
    setConfirmEmployer('')
    setConfirmRole('')
    setConfirmEvidenceType('')
    setMatchesApplication(false)
    setAcknowledgement('')
    setNotes('')
  }, [selectedEvidenceId])

  const preflightQuery = useQuery({
    queryKey: ['submission-evidence-review-preflight', applicationId, selectedEvidenceId],
    queryFn: () => getSubmissionEvidenceReviewPreflight(applicationId, selectedEvidenceId),
    select: (response) => response.data,
    enabled: Boolean(applicationId && selectedEvidenceId),
    retry: false,
  })

  const preflight = preflightQuery.data
  const confirmationsMatch = Boolean(
    preflight
      && confirmEmployer === preflight.employer
      && confirmRole === preflight.role
      && confirmEvidenceType === preflight.evidence?.evidence_type
      && matchesApplication
      && acknowledgement === 'REVIEWED',
  )
  const canSubmitReview = confirmationsMatch
    && (decision === 'rejected' || preflight?.ready_for_acceptance)

  const reviewMutation = useMutation({
    mutationFn: () => createSubmissionEvidenceReview(applicationId, selectedEvidenceId, {
      decision,
      confirm_employer: confirmEmployer,
      confirm_role: confirmRole,
      confirm_evidence_type: confirmEvidenceType,
      confirm_evidence_matches_application: matchesApplication,
      review_acknowledgement: acknowledgement,
      notes: notes || null,
    }),
    onSuccess: () => {
      toast.success(decision === 'accepted' ? 'Evidence accepted and application confirmed.' : 'Evidence rejected and routed to review.')
      qc.invalidateQueries({ queryKey: ['application', String(applicationId)] })
      qc.invalidateQueries({ queryKey: ['application', applicationId] })
      qc.invalidateQueries({ queryKey: ['submission-evidence-reviews', applicationId] })
      qc.invalidateQueries({ queryKey: ['submission-evidence-review-preflight', applicationId, selectedEvidenceId] })
    },
    onError: (error) => toast.error(error.response?.data?.detail || 'Evidence review failed'),
  })

  const exportMutation = useMutation({
    mutationFn: () => exportSupervisedPilotRecord(applicationId),
    onSuccess: (response) => {
      const payload = JSON.stringify(response.data, null, 2)
      const blob = new Blob([`${payload}\n`], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `greenhouse-supervised-pilot-${applicationId}.json`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      toast.success('Supervised pilot record exported.')
    },
    onError: (error) => toast.error(error.response?.data?.detail || 'Pilot export is not ready'),
  })

  if (!evidenceQuery.isLoading && evidence.length === 0) return null

  const reviews = reviewsQuery.data || []
  const acceptedValidReview = reviews.find(
    (review) => review.decision === 'accepted' && review.valid_for_current_evidence,
  )

  return (
    <section className="card overflow-hidden border border-slate-200">
      <div className="border-b border-slate-200 bg-slate-950 px-5 py-4 text-white">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="h-5 w-5" />
          <h2 className="font-semibold">Independent submission evidence review</h2>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-slate-300">
          Review concrete confirmation evidence separately from the automated worker. Raw applicant answers and browser credentials are never shown here.
        </p>
      </div>

      <div className="space-y-5 p-5">
        {evidenceQuery.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading retained evidence…
          </div>
        ) : (
          <div>
            <label className="label">Evidence record</label>
            <select
              className="input"
              value={selectedEvidenceId || ''}
              onChange={(event) => setSelectedEvidenceId(Number(event.target.value))}
            >
              {evidence.map((item) => (
                <option key={item.id} value={item.id}>
                  #{item.id} · {item.evidence_type} · {item.is_sufficient ? 'sufficient' : 'review required'}
                </option>
              ))}
            </select>
            {selectedEvidence && <div className="mt-3"><EvidenceSummary evidence={selectedEvidence} /></div>}
          </div>
        )}

        {preflightQuery.isLoading && selectedEvidenceId ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Computing immutable evidence snapshot…
          </div>
        ) : preflight ? (
          <>
            <div className={`rounded-lg border p-4 ${preflight.ready_for_acceptance ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'}`}>
              <div className="flex items-center gap-2 font-semibold text-slate-900">
                {preflight.ready_for_acceptance ? <ShieldCheck className="h-4 w-4 text-emerald-700" /> : <AlertTriangle className="h-4 w-4 text-amber-700" />}
                {preflight.ready_for_acceptance ? 'Evidence can enter acceptance review' : 'Acceptance is currently blocked'}
              </div>
              <div className="mt-3 grid gap-2 text-xs text-slate-700 md:grid-cols-2">
                <span>Application state: <strong>{preflight.application_state}</strong></span>
                <span>Consumed approval: <strong>{preflight.approval_reference || 'Missing'}</strong></span>
                <span>Evidence snapshot: <strong title={preflight.evidence?.evidence_snapshot_hash}>{compactHash(preflight.evidence?.evidence_snapshot_hash)}</strong></span>
                <span>Approved payload: <strong title={preflight.application_payload_hash}>{compactHash(preflight.application_payload_hash)}</strong></span>
                <span>Confirmation text: <strong>{preflight.evidence?.confirmation_text_present ? 'Present, stored as hash' : 'Not present'}</strong></span>
                <span>Confirmation hash: <strong title={preflight.evidence?.confirmation_text_hash}>{compactHash(preflight.evidence?.confirmation_text_hash)}</strong></span>
              </div>
              {preflight.blockers?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {preflight.blockers.map((blocker) => (
                    <span key={blocker} className="rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800">
                      {blockerLabel(blocker)}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <div>
                <label className="label">Type exact employer</label>
                <input className="input" value={confirmEmployer} onChange={(event) => setConfirmEmployer(event.target.value)} autoComplete="off" />
              </div>
              <div>
                <label className="label">Type exact role</label>
                <input className="input" value={confirmRole} onChange={(event) => setConfirmRole(event.target.value)} autoComplete="off" />
              </div>
              <div>
                <label className="label">Type exact evidence type</label>
                <input className="input" value={confirmEvidenceType} onChange={(event) => setConfirmEvidenceType(event.target.value)} autoComplete="off" />
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
              <div className="font-semibold text-slate-900">Expected values</div>
              <div className="mt-1 space-y-1">
                <div>Employer: <span className="font-mono">{preflight.employer}</span></div>
                <div>Role: <span className="font-mono">{preflight.role}</span></div>
                <div>Evidence type: <span className="font-mono">{preflight.evidence?.evidence_type}</span></div>
              </div>
            </div>

            <label className="flex items-start gap-2 text-sm text-slate-700">
              <input type="checkbox" className="mt-1" checked={matchesApplication} onChange={(event) => setMatchesApplication(event.target.checked)} />
              <span>I independently verified that this retained evidence belongs to this exact employer, role, application, approval, and payload fingerprint.</span>
            </label>

            <div>
              <label className="label">Type REVIEWED</label>
              <input className="input font-mono" value={acknowledgement} onChange={(event) => setAcknowledgement(event.target.value)} autoComplete="off" />
            </div>

            <div>
              <label className="label">Review notes</label>
              <textarea className="input min-h-[90px] resize-y" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Record what was inspected and why the decision is defensible." />
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <button
                type="button"
                onClick={() => setDecision('accepted')}
                className={`rounded-lg border p-3 text-left ${decision === 'accepted' ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 bg-white'}`}
              >
                <div className="flex items-center gap-2 font-semibold text-emerald-800"><CheckCircle2 className="h-4 w-4" /> Accept evidence</div>
                <p className="mt-1 text-xs text-slate-600">Only available when every concrete-evidence and approval gate passes.</p>
              </button>
              <button
                type="button"
                onClick={() => setDecision('rejected')}
                className={`rounded-lg border p-3 text-left ${decision === 'rejected' ? 'border-rose-400 bg-rose-50' : 'border-slate-200 bg-white'}`}
              >
                <div className="flex items-center gap-2 font-semibold text-rose-800"><XCircle className="h-4 w-4" /> Reject evidence</div>
                <p className="mt-1 text-xs text-slate-600">Routes the application to submission uncertainty and manual review.</p>
              </button>
            </div>

            <button
              type="button"
              onClick={() => reviewMutation.mutate()}
              disabled={!canSubmitReview || reviewMutation.isPending}
              className="btn-primary flex w-full items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {reviewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />}
              Record {decision} evidence review
            </button>
          </>
        ) : null}

        {reviews.length > 0 && (
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Fingerprint className="h-4 w-4" /> Review ledger</h3>
            <div className="mt-2 space-y-2">
              {reviews.map((review) => (
                <div key={review.reference} className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-600">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className={`rounded-full px-2 py-0.5 font-semibold ${review.decision === 'accepted' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>{review.decision}</span>
                    <span className={review.valid_for_current_evidence ? 'text-emerald-700' : 'text-rose-700'}>
                      {review.valid_for_current_evidence ? 'Valid for current snapshot' : 'Invalidated by evidence change'}
                    </span>
                  </div>
                  <div className="mt-2 grid gap-1 md:grid-cols-2">
                    <span>Reference: <strong>{review.reference}</strong></span>
                    <span>Reviewed: {formatDate(review.reviewed_at)}</span>
                    <span>Approval: {review.approval_reference || 'None'}</span>
                    <span>Snapshot: {compactHash(review.evidence_snapshot_hash)}</span>
                  </div>
                  {review.review_notes && <p className="mt-2 whitespace-pre-wrap text-slate-700">{review.review_notes}</p>}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-4">
          <div className="flex items-center gap-2 font-semibold text-indigo-950">
            <Download className="h-4 w-4" /> Supervised pilot ledger export
          </div>
          <p className="mt-1 text-xs leading-relaxed text-indigo-800">
            Export is available only after a currently valid accepted review confirms the application. The JSON contains hashes and references, not raw answers.
          </p>
          <button
            type="button"
            onClick={() => exportMutation.mutate()}
            disabled={!acceptedValidReview || application.automation_state !== 'confirmed' || exportMutation.isPending}
            className="btn-secondary mt-3 flex w-full items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {exportMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Export canonical supervised pilot record
          </button>
        </div>
      </div>
    </section>
  )
}
