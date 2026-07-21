import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  getApplication, updateApplication, generateCoverLetter,
  submitApplication, createFollowup
} from '../api/client'
import ManualHandoffPanel from '../components/ManualHandoffPanel'
import SupervisedSubmissionPanel from '../components/SupervisedSubmissionPanel'
import SubmissionEvidenceReviewPanel from '../components/SubmissionEvidenceReviewPanel'
import StatusBadge from '../components/StatusBadge'
import {
  ArrowLeft, Loader2, RefreshCw, Send, Calendar,
  FileText, ExternalLink, AlertCircle, CheckCircle2, LockKeyhole
} from 'lucide-react'
import { format, addDays } from 'date-fns'

const STATUSES = ['pending', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn']

function isGreenhouseUrl(value) {
  try {
    return new URL(value || '').hostname.toLowerCase().includes('greenhouse.io')
  } catch {
    return /greenhouse\.io/i.test(String(value || ''))
  }
}

function isFinishedApplication(application) {
  return application?.status === 'applied'
    || ['submitted', 'confirmed'].includes(application?.automation_state)
}

export default function ApplicationDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const [notes, setNotes] = useState('')
  const [newStatus, setNewStatus] = useState('')
  const [followupEmail, setFollowupEmail] = useState('')
  const [followupDate, setFollowupDate] = useState(format(addDays(new Date(), 7), "yyyy-MM-dd'T'HH:mm"))
  const [submitting, setSubmitting] = useState(false)

  const { data: app, isLoading } = useQuery({
    queryKey: ['application', id],
    queryFn: () => getApplication(id),
    select: (r) => r.data,
  })

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
      toast('Cover letter generation started. Refresh in a moment.')
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

  const handleSubmit = async (dry = false) => {
    if (isFinishedApplication(app)) {
      toast('This application is already recorded as submitted.')
      return
    }

    setSubmitting(true)
    try {
      await submitApplication(id, dry)
      toast(dry ? 'Dry run started. Check the application for progress.' : 'Application submission started!')
      setTimeout(() => qc.invalidateQueries(['application', id]), 3000)
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-tomato-500" />
      </div>
    )
  }
  if (!app) return <div className="text-center py-20 text-gray-500">Application not found.</div>

  const job = app.job
  const greenhouseApplication = isGreenhouseUrl(job?.url)
  const applicationFinished = isFinishedApplication(app)

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
            {job?.url && (
              <a href={job.url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-tomato-600 hover:underline mt-2">
                View original posting <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>
      </div>

      {!applicationFinished && <ManualHandoffPanel applicationId={Number(id)} />}
      {!applicationFinished && <SupervisedSubmissionPanel application={app} />}
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
              placeholder="Add notes, contact info, interview details…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <button
            onClick={() => updateMut.mutate({ status: newStatus, notes })}
            disabled={updateMut.isPending}
            className="btn-primary w-full"
          >
            {updateMut.isPending ? 'Saving…' : 'Save Changes'}
          </button>
        </div>

        <div className="card p-5 space-y-3">
          <h2 className="font-semibold text-gray-900">Actions</h2>
          <button
            onClick={() => genCLMut.mutate()}
            disabled={genCLMut.isPending}
            className="btn-secondary w-full flex items-center gap-2 justify-center"
          >
            {genCLMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            {app.cover_letter ? 'Regenerate Cover Letter' : 'Generate Cover Letter'}
          </button>

          {!applicationFinished && (
            <button
              onClick={() => handleSubmit(true)}
              disabled={submitting}
              className="btn-secondary w-full flex items-center gap-2 justify-center text-yellow-700 border-yellow-200 hover:bg-yellow-50"
            >
              <AlertCircle className="w-4 h-4" />
              Dry Run (Preview)
            </button>
          )}

          {!applicationFinished && greenhouseApplication && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-xs leading-relaxed text-slate-600">
              <div className="flex items-center gap-2 font-semibold text-slate-800">
                <LockKeyhole className="h-4 w-4" />
                Direct Greenhouse live submit is locked
              </div>
              <p className="mt-1">Use the supervised panel above. It requires exact confirmations, payload hashes, two feature flags, and a one-time approval.</p>
            </div>
          )}

          {!applicationFinished && !greenhouseApplication && (
            <button
              onClick={() => handleSubmit(false)}
              disabled={submitting}
              className="btn-primary w-full flex items-center gap-2 justify-center"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              Submit Application
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
            <FileText className="w-4 h-4" /> Cover Letter
          </h2>
        </div>
        {app.cover_letter ? (
          <pre className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed font-sans bg-gray-50 rounded-lg p-4">
            {app.cover_letter}
          </pre>
        ) : (
          <div className="text-center py-6 text-gray-400 text-sm">
            No cover letter yet.{' '}
            <button onClick={() => genCLMut.mutate()} className="text-tomato-600 hover:underline">
              Generate one with AI
            </button>
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
            {followupMut.isPending ? 'Scheduling…' : 'Schedule Follow-up Email'}
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
