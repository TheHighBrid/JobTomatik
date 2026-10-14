import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  getApplication, updateApplication, generateCoverLetter,
  applyJT5Application, getJT5ApplicationStatus, createFollowup, getApiErrorMessage
} from '../api/client'
import ManualHandoffPanel from '../components/ManualHandoffPanel'
import OperatorFinalSubmitHandoffPanel from '../components/OperatorFinalSubmitHandoffPanel'
import SubmissionEvidenceReviewPanel from '../components/SubmissionEvidenceReviewPanel'
import StatusBadge from '../components/StatusBadge'
import {
  HANDOFF_REVIEW_REASONS,
  canOpenManualReviewPage,
  routeApplicationManualReviews,
} from '../applicationManualReviewRouting'
import {
  ArrowLeft, Loader2, RefreshCw, Send, Calendar,
  FileText, ExternalLink, AlertCircle, CheckCircle2, Route
} from 'lucide-react'
import { format, addDays } from 'date-fns'
import { detectSupervisedPlatform } from '../supervisedPlatforms'

const STATUSES = ['pending', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn']

function isLinkedInUrl(value) {
  try {
    return new URL(value || '').hostname.toLowerCase().includes('linkedin.com')
  } catch {
    return /linkedin\.com/i.test(String(value || ''))
  }
}

function isFinishedApplication(application) {
  return application?.status === 'applied'
    || ['submitted', 'confirmed'].includes(application?.automation_state)
}

function targetStatusLabel(status) {
  return String(status || 'unresolved').replaceAll('_', ' ')
}

function targetStatusClasses(status) {
  if (status === 'resolved') return 'bg-green-100 text-green-700'
  if (status === 'resolving') return 'bg-blue-100 text-blue-700'
  if (status === 'requires_human') return 'bg-amber-100 text-amber-700'
  if (status === 'failed') return 'bg-red-100 text-red-700'
  return 'bg-gray-100 text-gray-600'
}

export default function ApplicationDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const [notes, setNotes] = useState('')
  const [newStatus, setNewStatus] = useState('')
  const [followupEmail, setFollowupEmail] = useState('')
  const [followupDate, setFollowupDate] = useState(format(addDays(new Date(), 7), "yyyy-MM-dd'T'HH:mm"))
  const { data: app, isLoading } = useQuery({
    queryKey: ['application', id],
    queryFn: () => getApplication(id),
    select: (r) => r.data,
    refetchInterval: (query) => {
      const value = query.state.data?.data || query.state.data
      return value?.automation_state === 'applying' ? 1500 : false
    },
    refetchIntervalInBackground: true,
  })

  const { data: jt5Status } = useQuery({
    queryKey: ['jt5-application-status', id],
    queryFn: () => getJT5ApplicationStatus(id),
    select: (response) => response.data,
    enabled: Boolean(app),
    refetchInterval: (query) => {
      const attempt = query.state.data?.latest_attempt
      const active = ['queued', 'in_progress'].includes(attempt?.status)
        && attempt?.dispatch_status !== 'reconciliation_required'
      return active ? 1500 : false
    },
    refetchIntervalInBackground: true,
    retry: 2,
  })
  const jt5Attempt = jt5Status?.latest_attempt || null
  const jt5ReconciliationRequired = jt5Attempt?.dispatch_status === 'reconciliation_required'
    || jt5Attempt?.status === 'uncertain'
  const jt5AttemptActive = ['queued', 'in_progress'].includes(jt5Attempt?.status)
    && !jt5ReconciliationRequired

  useEffect(() => {
    if (!jt5Attempt || jt5AttemptActive) return
    qc.invalidateQueries({ queryKey: ['application', id] })
    qc.invalidateQueries({ queryKey: ['applications'] })
  }, [jt5Attempt?.reference, jt5Attempt?.status, jt5AttemptActive, id, qc])

  useEffect(() => {
    if (app) {
      setNotes(app.notes || '')
      setNewStatus(app.status)
    }
  }, [app?.id])

  const updateMut = useMutation({
    mutationFn: (data) => updateApplication(id, data),
    onSuccess: () => {
      toast.success('Application updated!')
      qc.invalidateQueries(['application', id])
      qc.invalidateQueries(['applications'])
    },
  })

  const genCLMut = useMutation({
    mutationFn: () => generateCoverLetter(id),
    onSuccess: () => {
      toast('Verified cover-letter generation started. Source-backed claims will be used, and insufficient evidence will route to review.')
      setTimeout(() => qc.invalidateQueries(['application', id]), 5000)
    },
  })

  const followupMut = useMutation({
    mutationFn: () => createFollowup(id, {
      scheduled_at: new Date(followupDate).toISOString(),
      subject: `Following up on my ${app?.job?.title} application`,
      message: null,
      recipient_email: followupEmail,
    }),
    onSuccess: () => {
      toast.success('Follow-up scheduled!')
      qc.invalidateQueries(['application', id])
      setFollowupEmail('')
    },
  })

  const applyMutation = useMutation({
    mutationFn: () => applyJT5Application(id),
    onSuccess: async (response) => {
      const result = response.data || {}
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['jt5-application-status', id] }),
        qc.invalidateQueries({ queryKey: ['application', id] }),
        qc.invalidateQueries({ queryKey: ['handoffs', Number(id)] }),
        qc.invalidateQueries({ queryKey: ['applications'] }),
      ])
      if (result.status === 'queued') {
        toast('Application attempt started. JobTomatik is preparing the selected employer target.')
      } else if (result.status === 'already_confirmed') {
        toast('This application is already recorded as submitted.')
      } else if (result.status === 'in_progress') {
        toast('An application attempt is already in progress. No duplicate attempt was started.')
      } else if (result.status === 'reconcile') {
        toast.error('The prior outcome is uncertain. Reconcile it before starting another attempt.')
      } else {
        toast.error('The backend returned an unrecognized application status.')
      }
    },
    onError: async (error) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['jt5-application-status', id] }),
        qc.invalidateQueries({ queryKey: ['application', id] }),
        qc.invalidateQueries({ queryKey: ['applications'] }),
      ])
      toast.error(getApiErrorMessage(error, 'Application attempt could not be started.'))
    },
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-tomato-500" />
      </div>
    )
  }
  if (!app) return <div className="text-center py-20 text-gray-500">Application not found.</div>

  const job = app.job
  const effectiveTargetUrl = app.application_target_url || job?.url
  const supervisedPlatform = detectSupervisedPlatform(effectiveTargetUrl)
  const applicationFinished = isFinishedApplication(app) || jt5Attempt?.status === 'succeeded'
  const {
    activeManualReview,
    operatorFinalSubmitReview,
    activeHandoffReview,
    handoffExpected,
  } = routeApplicationManualReviews(app.manual_reviews || [])
  const targetNavigationReview = activeManualReview?.reason_code === 'application_target_required'
  const linkedInDiscoveryReview = (
    activeManualReview?.reason_code === 'unsupported_platform'
    && isLinkedInUrl(job?.url)
  )
  const leverCertificationLocked = supervisedPlatform === 'lever' && !applicationFinished
  const canOpenManualApplicationPage = canOpenManualReviewPage(
    activeManualReview,
    supervisedPlatform,
  )
  const submissionBusy = applyMutation.isPending || jt5AttemptActive || app.automation_state === 'applying'
  const targetStatus = app.application_target_status || 'unresolved'

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-fade-in">
      <Link to="/applications" className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft className="w-4 h-4" /> Back to Applications
      </Link>

      <div className="card p-6">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-tomato-100 flex items-center justify-center text-tomato-700 font-bold text-lg flex-shrink-0">
            {(job?.company || '?')[0]}
          </div>
          <div className="flex-1">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h1 className="text-xl font-bold text-gray-900">{job?.title || 'Unknown Position'}</h1>
                <p className="text-gray-600 mt-0.5">{job?.company} · {job?.location}</p>
              </div>
              <StatusBadge status={app.status} />
            </div>
            {job?.url && !leverCertificationLocked && (
              <a href={job.url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-tomato-600 hover:underline mt-2">
                View original posting <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>
      </div>

      <section className="card p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <Route className="w-5 h-5 text-slate-600 mt-0.5 flex-shrink-0" />
            <div>
              <h2 className="font-semibold text-gray-900">Application destination</h2>
              <p className="text-sm text-gray-600 mt-1">
                JobTomatik keeps the discovery listing separate from the employer or ATS form it will operate.
              </p>
            </div>
          </div>
          <span className={`badge capitalize ${targetStatusClasses(targetStatus)}`}>
            {targetStatusLabel(targetStatus)}
          </span>
        </div>

        <div className="grid gap-3 text-sm">
          <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-3">
            <div className="text-xs font-medium uppercase tracking-wide text-gray-400">Source listing</div>
            <div className="mt-1 break-all text-gray-700">{app.source_listing_url || job?.url || 'Not recorded yet'}</div>
          </div>
          <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-3">
            <div className="text-xs font-medium uppercase tracking-wide text-gray-400">Employer application target</div>
            {app.application_target_url ? (
              leverCertificationLocked ? (
                <div className="mt-1">
                  <div className="break-all text-gray-700">{app.application_target_url}</div>
                  <div className="mt-1 text-xs text-emerald-700">
                    Direct employer-page opening is locked during supervised Lever Phase B. Use the retained operator-assisted controls below.
                  </div>
                </div>
              ) : (
                <a
                  href={app.application_target_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 inline-flex items-start gap-1 break-all text-tomato-600 hover:underline"
                >
                  {app.application_target_url}
                  <ExternalLink className="w-3 h-3 mt-1 flex-shrink-0" />
                </a>
              )
            ) : (
              <div className="mt-1 text-gray-500">
                {targetStatus === 'requires_human'
                  ? 'A verified human-only security boundary was detected while resolving the employer destination.'
                  : targetStatus === 'resolving'
                    ? 'Resolving the employer destination now...'
                    : 'Not resolved yet.'}
              </div>
            )}
          </div>
        </div>
      </section>

      {activeManualReview && (
        <section className="card overflow-hidden border border-amber-200">
          <div className="bg-amber-50 px-5 py-4 border-b border-amber-100">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-700 mt-0.5 flex-shrink-0" />
              <div className="min-w-0 flex-1">
                <h2 className="font-semibold text-gray-900">
                  {operatorFinalSubmitReview ? 'Owner final action required' : 'Manual review required'}
                </h2>
                <p className="text-sm text-gray-700 mt-1">
                  {activeManualReview.summary}
                </p>
                <p className="text-sm text-gray-600 mt-2">
                  {targetNavigationReview
                    ? 'This is an obsolete navigation-only review from an older attempt. Start a new dry run so JobTomatik can resolve the Apply doorway automatically.'
                    : linkedInDiscoveryReview
                      ? 'This older attempt treated LinkedIn as an unsupported form. Start a new dry run to use the persistent target resolver.'
                      : operatorFinalSubmitReview
                        ? 'The exact employer form is already filled and retained. Use the operator-assisted approval and secure final-submit handoff below. Do not open a fresh application page.'
                        : leverCertificationLocked && activeHandoffReview?.id === activeManualReview.id
                          ? 'Use the secure handoff below to complete the protected challenge inside the retained browser. Do not open the employer application in another tab.'
                          : leverCertificationLocked
                            ? 'Use the operator-assisted controls below. Direct employer-page opening is disabled for Lever Phase B so answer review, challenge handling, approval, and final action stay inside one certifiable transaction.'
                            : HANDOFF_REVIEW_REASONS.has(activeManualReview.reason_code)
                              ? 'Use the secure handoff below instead of opening a second employer page.'
                              : 'This attempt reached a step that JobTomatik cannot complete automatically. Review the reason below and open the application page when manual action is required.'}
                </p>
                <div className="text-xs text-gray-500 mt-2">
                  Reason: {activeManualReview.reason_code.replaceAll('_', ' ')}
                </div>
              </div>
            </div>
          </div>

          {canOpenManualApplicationPage && (
            <div className="px-5 py-4">
              <a
                href={activeManualReview.blocking_url}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-secondary inline-flex items-center gap-2"
              >
                Open application page
                <ExternalLink className="w-4 h-4" />
              </a>
            </div>
          )}
        </section>
      )}

      {!applicationFinished && operatorFinalSubmitReview && (
        <OperatorFinalSubmitHandoffPanel applicationId={Number(id)} />
      )}
      {!applicationFinished && handoffExpected && (
        <ManualHandoffPanel applicationId={Number(id)} />
      )}
      <SubmissionEvidenceReviewPanel application={app} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="card p-5 space-y-4">
          <h2 className="font-semibold text-gray-900">Status</h2>
          <select
            className="input"
            value={newStatus}
            onChange={(e) => setNewStatus(e.target.value)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
            ))}
          </select>
          <div>
            <label className="label">Notes</label>
            <textarea
              className="input min-h-[100px] resize-none"
              placeholder="Add notes, contact info, interview details..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <button
            onClick={() => updateMut.mutate({ status: newStatus, notes })}
            disabled={updateMut.isPending}
            className="btn-primary w-full"
          >
            {updateMut.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>

        <div className="card p-5 space-y-3">
          <h2 className="font-semibold text-gray-900">Actions</h2>

          {(jt5AttemptActive || (app.automation_state === 'applying' && !operatorFinalSubmitReview)) && (
            <div className="flex items-start gap-2 rounded-lg border border-blue-100 bg-blue-50 px-3 py-3 text-sm text-blue-800">
              <Loader2 className="w-4 h-4 animate-spin mt-0.5 flex-shrink-0" />
              <span>
                {app.automation_state === 'applying'
                  ? 'Application automation is running. This page is following the reserved attempt and will update automatically.'
                  : 'Application attempt is queued. JobTomatik is waiting for the managed worker to claim it.'}
              </span>
            </div>
          )}

          {jt5ReconciliationRequired && !applicationFinished && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900">
              The prior attempt needs reconciliation. JobTomatik will not start another attempt automatically.
            </div>
          )}

          <button
            onClick={() => genCLMut.mutate()}
            disabled={genCLMut.isPending}
            className="btn-secondary w-full flex items-center gap-2 justify-center"
          >
            {genCLMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            {app.cover_letter ? 'Regenerate Verified Cover Letter' : 'Generate Verified Cover Letter'}
          </button>

          {!applicationFinished && !jt5ReconciliationRequired && (
            <button
              onClick={() => applyMutation.mutate()}
              disabled={submissionBusy}
              className="btn-primary w-full flex items-center gap-2 justify-center"
            >
              {submissionBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              Apply with JobTomatik
            </button>
          )}

          {applicationFinished && (
            <div className="flex items-center gap-2 text-green-700 text-sm bg-green-50 border border-green-100 px-3 py-3 rounded-lg">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              <span>Application submitted. New submission attempts are hidden for this record.</span>
            </div>
          )}
        </div>
      </div>

      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <FileText className="w-4 h-4" /> Verified Cover Letter
          </h2>
          <Link
            to={`/evidence-materials?application=${id}`}
            className="text-xs font-semibold text-tomato-600 hover:underline"
          >
            Open claim audit
          </Link>
        </div>
        {app.cover_letter ? (
          <pre className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed font-sans bg-gray-50 rounded-lg p-4">
            {app.cover_letter}
          </pre>
        ) : (
          <div className="text-center py-6 text-gray-400 text-sm">
            No verified cover letter yet.{' '}
            <Link to={`/evidence-materials?application=${id}`} className="text-tomato-600 hover:underline">
              Build source-backed materials
            </Link>
          </div>
        )}
      </div>

      <div className="card p-5">
        <h2 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Calendar className="w-4 h-4" /> Schedule Follow-up
        </h2>
        <div className="space-y-3">
          <div>
            <label className="label">Recruiter/HR Email</label>
            <input
              type="email"
              className="input"
              placeholder="recruiter@company.com"
              value={followupEmail}
              onChange={(e) => setFollowupEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Send on</label>
            <input
              type="datetime-local"
              className="input"
              value={followupDate}
              onChange={(e) => setFollowupDate(e.target.value)}
            />
          </div>
          <button
            onClick={() => followupMut.mutate()}
            disabled={!followupEmail || followupMut.isPending}
            className="btn-primary w-full"
          >
            {followupMut.isPending ? 'Scheduling...' : 'Schedule Follow-up Email'}
          </button>
        </div>

        {app.followups?.length > 0 && (
          <div className="mt-5">
            <h3 className="text-sm font-medium text-gray-700 mb-2">Scheduled Follow-ups</h3>
            <div className="space-y-2">
              {app.followups.map((f) => (
                <div key={f.id} className="flex items-center gap-3 text-sm p-2.5 rounded-lg bg-gray-50">
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${f.status === 'sent' ? 'bg-green-500' : f.status === 'failed' ? 'bg-red-500' : 'bg-yellow-400'}`} />
                  <div className="flex-1 min-w-0">
                    <div className="text-gray-700 truncate">{f.recipient_email}</div>
                    <div className="text-xs text-gray-400">
                      {f.sent_at ? `Sent ${format(new Date(f.sent_at), 'MMM d, h:mm a')}` : `Scheduled ${format(new Date(f.scheduled_at), 'MMM d, h:mm a')}`}
                    </div>
                  </div>
                  <span className={`badge text-xs ${f.status === 'sent' ? 'bg-green-100 text-green-700' : f.status === 'failed' ? 'bg-red-100 text-red-600' : 'bg-yellow-100 text-yellow-700'}`}>
                    {f.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {job?.description && (
        <div className="card p-5">
          <h2 className="font-semibold text-gray-900 mb-3">Job Description</h2>
          <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">
            {job.description}
          </div>
          {job.skills?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-4">
              {job.skills.map((s) => (
                <span key={s} className="badge bg-blue-50 text-blue-700">{s}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
