import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  GitCompareArrows,
  Inbox,
  Loader2,
  MailPlus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trophy,
} from 'lucide-react'

import { getApiErrorMessage } from '../api/client'
import {
  confirmEmployerMessageStatus,
  getInterviewPrep,
  getOfferComparison,
  getPostApplicationWorkspace,
  ingestEmployerMessage,
  recordPostApplicationOutcome,
  schedulePostApplicationInterview,
} from '../api/postApplication'

const TABS = [
  { id: 'inbox', label: 'Employer inbox', icon: Inbox },
  { id: 'interviews', label: 'Interviews', icon: CalendarClock },
  { id: 'offers', label: 'Offers & outcomes', icon: GitCompareArrows },
]

function formatDate(value) {
  if (!value) return 'Not scheduled'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown time'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

function statusClass(value) {
  const status = String(value || '').toLowerCase()
  if (['offer', 'confirmed'].includes(status)) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (['interviewing', 'applied', 'interview'].includes(status)) return 'border-blue-200 bg-blue-50 text-blue-700'
  if (['assessment', 'status_update', 'application_received'].includes(status)) return 'border-amber-200 bg-amber-50 text-amber-700'
  if (['rejected', 'withdrawn', 'rejection'].includes(status)) return 'border-red-200 bg-red-50 text-red-700'
  return 'border-gray-200 bg-gray-50 text-gray-600'
}

function Card({ children, className = '' }) {
  return <div className={`rounded-2xl border border-gray-200 bg-white p-4 shadow-sm ${className}`}>{children}</div>
}

function Metric({ label, value, detail, icon: Icon }) {
  return (
    <Card>
      <div className="flex items-center justify-between gap-3">
        <div className="brand-icon-well h-9 w-9"><Icon className="h-4 w-4" /></div>
        <div className="text-xl font-bold text-gray-900">{value}</div>
      </div>
      <div className="mt-3 text-sm font-semibold text-gray-900">{label}</div>
      <div className="mt-0.5 text-xs text-gray-500">{detail}</div>
    </Card>
  )
}

function ApplicationSelect({ applications, value, onChange, id, label = 'Application' }) {
  return (
    <label className="block text-xs font-semibold text-gray-700" htmlFor={id}>
      {label}
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-tomato-400"
      >
        <option value="">Select an application</option>
        {applications.map((application) => (
          <option key={application.application_id} value={application.application_id}>
            {application.company} · {application.title} · {application.status}
          </option>
        ))}
      </select>
    </label>
  )
}

function EmployerInbox({ workspace, refresh }) {
  const queryClient = useQueryClient()
  const applications = workspace.applications || []
  const messages = (workspace.events || []).filter((event) => event.event_type === 'inbound_employer_message')
  const [form, setForm] = useState({
    applicationId: '',
    senderName: '',
    senderEmail: '',
    subject: '',
    body: '',
    sourceReference: '',
  })
  const [lastMessage, setLastMessage] = useState(null)
  const [error, setError] = useState('')

  const ingest = useMutation({
    mutationFn: () => ingestEmployerMessage(Number(form.applicationId), {
      sender_name: form.senderName || null,
      sender_email: form.senderEmail,
      subject: form.subject,
      body: form.body,
      source_reference: form.sourceReference,
      create_recruiter_contact: true,
    }),
    onSuccess: (response) => {
      setError('')
      setLastMessage(response.data)
      queryClient.invalidateQueries({ queryKey: ['post-application-workspace'] })
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not record employer message')),
  })

  const confirm = useMutation({
    mutationFn: ({ eventId, proposedStatus }) => confirmEmployerMessageStatus(
      Number(form.applicationId || lastMessage?.application_id),
      eventId,
      `CONFIRM STATUS ${String(proposedStatus).toUpperCase()}`,
    ),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['post-application-workspace'] })
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not confirm status')),
  })

  return (
    <div className="grid gap-4 xl:grid-cols-[0.95fr_1.35fr]">
      <Card>
        <div className="flex items-center gap-2">
          <MailPlus className="h-4 w-4 text-tomato-600" />
          <h2 className="text-sm font-bold text-gray-900">Record employer email</h2>
        </div>
        <p className="mt-2 text-xs leading-5 text-gray-500">
          Attach the message to the exact application. Classification is deterministic and read-only until you explicitly confirm a proposed status.
        </p>
        <div className="mt-4 space-y-3">
          <ApplicationSelect
            applications={applications}
            value={form.applicationId}
            onChange={(value) => setForm((current) => ({ ...current, applicationId: value }))}
            id="post-application-message-app"
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-semibold text-gray-700">
              Sender name
              <input
                value={form.senderName}
                onChange={(event) => setForm((current) => ({ ...current, senderName: event.target.value }))}
                className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm"
                placeholder="Recruiter name"
              />
            </label>
            <label className="text-xs font-semibold text-gray-700">
              Sender email
              <input
                type="email"
                value={form.senderEmail}
                onChange={(event) => setForm((current) => ({ ...current, senderEmail: event.target.value }))}
                className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm"
                placeholder="recruiter@company.com"
              />
            </label>
          </div>
          <label className="block text-xs font-semibold text-gray-700">
            Subject
            <input
              value={form.subject}
              onChange={(event) => setForm((current) => ({ ...current, subject: event.target.value }))}
              className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm"
            />
          </label>
          <label className="block text-xs font-semibold text-gray-700">
            Message body
            <textarea
              rows={6}
              value={form.body}
              onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))}
              className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm"
            />
          </label>
          <label className="block text-xs font-semibold text-gray-700">
            Source reference
            <input
              value={form.sourceReference}
              onChange={(event) => setForm((current) => ({ ...current, sourceReference: event.target.value }))}
              className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm"
              placeholder="email message id, provider reference, or user note"
            />
          </label>
          {error && <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
          <button
            type="button"
            disabled={ingest.isPending || !form.applicationId || !form.senderEmail || !form.subject || !form.body || !form.sourceReference}
            onClick={() => ingest.mutate()}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-tomato-600 px-4 py-2.5 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {ingest.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <MailPlus className="h-4 w-4" />}
            Classify and record
          </button>
        </div>

        {lastMessage && (
          <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full border px-2 py-0.5 text-[11px] font-bold ${statusClass(lastMessage.classification.category)}`}>
                {lastMessage.classification.category.replaceAll('_', ' ')}
              </span>
              <span className="text-xs text-gray-500">{Math.round(lastMessage.classification.confidence * 100)}% rule confidence</span>
              {lastMessage.duplicate && <span className="text-xs font-semibold text-amber-600">Already recorded</span>}
            </div>
            {lastMessage.classification.proposed_status && (
              <div className="mt-3">
                <p className="text-xs text-gray-600">
                  Proposed status: <strong>{lastMessage.classification.proposed_status}</strong>. Nothing changes until confirmed.
                </p>
                <button
                  type="button"
                  disabled={confirm.isPending}
                  onClick={() => confirm.mutate({
                    eventId: lastMessage.event_id,
                    proposedStatus: lastMessage.classification.proposed_status,
                  })}
                  className="mt-2 inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700"
                >
                  {confirm.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                  Confirm {lastMessage.classification.proposed_status}
                </button>
              </div>
            )}
          </div>
        )}
      </Card>

      <Card>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Recent employer messages</h2>
            <p className="mt-1 text-xs text-gray-500">Stored with source references and classification provenance.</p>
          </div>
          <button type="button" onClick={refresh} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100" aria-label="Refresh inbox">
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-4 space-y-2.5">
          {messages.map((event) => {
            const payload = event.payload || {}
            const classification = payload.classification || {}
            return (
              <div key={event.event_id} className="rounded-xl border border-gray-200 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-gray-900">{payload.subject || 'Employer message'}</div>
                    <div className="mt-0.5 text-xs text-gray-500">{payload.sender_name || payload.sender_email}</div>
                  </div>
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${statusClass(classification.category)}`}>
                    {String(classification.category || 'other').replaceAll('_', ' ')}
                  </span>
                </div>
                <p className="mt-2 line-clamp-3 text-xs leading-5 text-gray-600">{payload.body_preview}</p>
                <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-gray-400">
                  <span>{formatDate(payload.received_at || event.created_at)}</span>
                  <span>•</span>
                  <span>{payload.source_reference}</span>
                  {payload.status_applied && <><span>•</span><span className="font-semibold text-emerald-600">status confirmed</span></>}
                </div>
              </div>
            )
          })}
          {!messages.length && (
            <div className="rounded-xl border border-dashed border-gray-300 p-8 text-center text-sm text-gray-400">
              No employer messages have been recorded yet.
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}

function Interviews({ workspace }) {
  const queryClient = useQueryClient()
  const applications = workspace.applications || []
  const interviewing = applications.filter((application) => application.status === 'interviewing')
  const [form, setForm] = useState({ applicationId: '', interviewAt: '', format: 'video', location: '', notes: '', sourceReference: '' })
  const [prepApplicationId, setPrepApplicationId] = useState('')
  const [error, setError] = useState('')

  const schedule = useMutation({
    mutationFn: () => schedulePostApplicationInterview(Number(form.applicationId), {
      interview_at: new Date(form.interviewAt).toISOString(),
      interview_format: form.format,
      location_or_url: form.location || null,
      notes: form.notes || null,
      source_reference: form.sourceReference,
    }),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['post-application-workspace'] })
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not schedule interview')),
  })

  const prep = useQuery({
    queryKey: ['post-application-interview-prep', prepApplicationId],
    queryFn: () => getInterviewPrep(Number(prepApplicationId)).then((response) => response.data),
    enabled: Boolean(prepApplicationId),
  })

  return (
    <div className="grid gap-4 xl:grid-cols-[0.95fr_1.35fr]">
      <Card>
        <h2 className="text-sm font-bold text-gray-900">Interview schedule</h2>
        <p className="mt-1 text-xs text-gray-500">A user-confirmed interview schedule moves the application into interviewing and records provenance.</p>
        <div className="mt-4 space-y-3">
          <ApplicationSelect
            applications={applications.filter((application) => !['offer', 'rejected', 'withdrawn'].includes(application.status))}
            value={form.applicationId}
            onChange={(value) => setForm((current) => ({ ...current, applicationId: value }))}
            id="post-application-interview-app"
          />
          <label className="block text-xs font-semibold text-gray-700">
            Interview date & time
            <input type="datetime-local" value={form.interviewAt} onChange={(event) => setForm((current) => ({ ...current, interviewAt: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-semibold text-gray-700">
              Format
              <select value={form.format} onChange={(event) => setForm((current) => ({ ...current, format: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm">
                <option value="video">Video</option><option value="phone">Phone</option><option value="onsite">Onsite</option><option value="other">Other</option>
              </select>
            </label>
            <label className="text-xs font-semibold text-gray-700">
              Location or URL
              <input value={form.location} onChange={(event) => setForm((current) => ({ ...current, location: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" />
            </label>
          </div>
          <label className="block text-xs font-semibold text-gray-700">Notes<input value={form.notes} onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" /></label>
          <label className="block text-xs font-semibold text-gray-700">Source reference<input value={form.sourceReference} onChange={(event) => setForm((current) => ({ ...current, sourceReference: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" /></label>
          {error && <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
          <button type="button" disabled={schedule.isPending || !form.applicationId || !form.interviewAt || !form.sourceReference} onClick={() => schedule.mutate()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-tomato-600 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50">
            {schedule.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarClock className="h-4 w-4" />} Save interview
          </button>
        </div>
      </Card>

      <div className="space-y-4">
        <Card>
          <h2 className="text-sm font-bold text-gray-900">Upcoming interviews</h2>
          <div className="mt-3 space-y-2.5">
            {interviewing.map((application) => (
              <div key={application.application_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 p-3">
                <div><div className="text-sm font-semibold text-gray-900">{application.title}</div><div className="text-xs text-gray-500">{application.company} · {formatDate(application.interview_at)}</div></div>
                <button type="button" onClick={() => setPrepApplicationId(String(application.application_id))} className="inline-flex items-center gap-1.5 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs font-bold text-violet-700"><Sparkles className="h-3.5 w-3.5" /> Prep packet</button>
              </div>
            ))}
            {!interviewing.length && <div className="rounded-xl border border-dashed border-gray-300 p-6 text-center text-sm text-gray-400">No interviews are currently scheduled.</div>}
          </div>
        </Card>

        {prepApplicationId && (
          <Card>
            <div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-violet-600" /><h2 className="text-sm font-bold text-gray-900">Source-backed interview prep</h2></div>
            {prep.isLoading && <div className="mt-4 flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" /> Building packet…</div>}
            {prep.isError && <div className="mt-3 text-xs text-red-600">{getApiErrorMessage(prep.error, 'Could not build interview prep')}</div>}
            {prep.data && (
              <div className="mt-4 space-y-4 text-sm">
                <div><div className="font-bold text-gray-900">{prep.data.company} · {prep.data.role}</div><div className="mt-1 text-xs text-gray-500">{prep.data.provenance_policy}</div></div>
                <div><div className="text-xs font-bold uppercase tracking-wide text-gray-500">Role requirements</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-gray-700">{prep.data.requirements.map((item) => <li key={item}>{item}</li>)}</ul></div>
                <div><div className="text-xs font-bold uppercase tracking-wide text-gray-500">Verified candidate evidence</div><div className="mt-2 space-y-2">{prep.data.candidate_evidence.map((item, index) => <div key={`${item.source_ref}-${index}`} className="rounded-lg bg-gray-50 p-2.5 text-xs text-gray-700">{item.content}<div className="mt-1 text-[10px] text-gray-400">{item.source} · {item.source_ref || 'no source reference'}</div></div>)}</div></div>
                <div><div className="text-xs font-bold uppercase tracking-wide text-gray-500">Questions to prepare</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-gray-700">{prep.data.question_prompts.map((item) => <li key={item}>{item}</li>)}</ul></div>
              </div>
            )}
          </Card>
        )}
      </div>
    </div>
  )
}

function OffersAndOutcomes({ workspace }) {
  const queryClient = useQueryClient()
  const applications = workspace.applications || []
  const [form, setForm] = useState({ applicationId: '', outcome: 'offer', salary: '', detail: '', sourceReference: '' })
  const [error, setError] = useState('')
  const offers = useQuery({
    queryKey: ['post-application-offers'],
    queryFn: () => getOfferComparison().then((response) => response.data),
  })
  const record = useMutation({
    mutationFn: () => recordPostApplicationOutcome(Number(form.applicationId), {
      outcome: form.outcome,
      salary_offered: form.outcome === 'offer' && form.salary ? Number(form.salary) : null,
      detail: form.detail || null,
      source_reference: form.sourceReference,
    }),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['post-application-workspace'] })
      queryClient.invalidateQueries({ queryKey: ['post-application-offers'] })
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not record outcome')),
  })

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center gap-2"><Trophy className="h-4 w-4 text-emerald-600" /><h2 className="text-sm font-bold text-gray-900">Offer comparison</h2></div>
        <p className="mt-1 text-xs text-gray-500">Recorded compensation and existing fit evidence are shown side by side. JobTomatik does not choose an offer for you.</p>
        {offers.isLoading && <div className="mt-4 flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading offers…</div>}
        {offers.data && (
          <div className="mt-4 overflow-x-auto rounded-xl border border-gray-200">
            <table className="min-w-[760px] w-full text-left text-xs">
              <thead className="bg-gray-50 text-gray-500"><tr><th className="px-3 py-2.5">Opportunity</th><th className="px-3 py-2.5">Offer</th><th className="px-3 py-2.5">Posted range</th><th className="px-3 py-2.5">Fit score</th><th className="px-3 py-2.5">Received</th></tr></thead>
              <tbody className="divide-y divide-gray-100">{offers.data.offers.map((offer) => <tr key={offer.application_id}><td className="px-3 py-3"><div className="font-semibold text-gray-900">{offer.title}</div><div className="text-gray-500">{offer.company}</div></td><td className="px-3 py-3 font-semibold text-gray-900">{offer.salary_offered ? `${offer.salary_currency || ''} ${offer.salary_offered.toLocaleString()}` : 'Not recorded'}</td><td className="px-3 py-3 text-gray-600">{offer.market_salary_min && offer.market_salary_max ? `${offer.market_salary_min.toLocaleString()}–${offer.market_salary_max.toLocaleString()}` : 'Unknown'}</td><td className="px-3 py-3 text-gray-600">{offer.weighted_fit_score ?? '—'}</td><td className="px-3 py-3 text-gray-500">{formatDate(offer.offer_received_at)}</td></tr>)}</tbody>
            </table>
            {!offers.data.offers.length && <div className="p-8 text-center text-sm text-gray-400">No offers recorded yet.</div>}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="text-sm font-bold text-gray-900">Record application outcome</h2>
        <p className="mt-1 text-xs text-gray-500">Outcome learning stores the exact observed result with its source reference. It does not generalize a new applicant fact.</p>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <ApplicationSelect applications={applications} value={form.applicationId} onChange={(value) => setForm((current) => ({ ...current, applicationId: value }))} id="post-application-outcome-app" />
          <label className="text-xs font-semibold text-gray-700">Outcome<select value={form.outcome} onChange={(event) => setForm((current) => ({ ...current, outcome: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm"><option value="offer">Offer</option><option value="rejected">Rejected</option><option value="withdrawn">Withdrawn</option></select></label>
          {form.outcome === 'offer' && <label className="text-xs font-semibold text-gray-700">Salary offered<input type="number" min="0" value={form.salary} onChange={(event) => setForm((current) => ({ ...current, salary: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" /></label>}
          <label className="text-xs font-semibold text-gray-700">Source reference<input value={form.sourceReference} onChange={(event) => setForm((current) => ({ ...current, sourceReference: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" /></label>
          <label className="text-xs font-semibold text-gray-700 lg:col-span-2">Detail<textarea rows={3} value={form.detail} onChange={(event) => setForm((current) => ({ ...current, detail: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" /></label>
        </div>
        {error && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        <button type="button" disabled={record.isPending || !form.applicationId || !form.sourceReference} onClick={() => record.mutate()} className="mt-3 inline-flex items-center gap-2 rounded-xl bg-tomato-600 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50">{record.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Record outcome</button>
      </Card>
    </div>
  )
}

export default function PostApplicationCenter() {
  const [tab, setTab] = useState('inbox')
  const workspace = useQuery({
    queryKey: ['post-application-workspace'],
    queryFn: () => getPostApplicationWorkspace().then((response) => response.data),
  })

  const summary = workspace.data?.summary || {}
  const metrics = useMemo(() => [
    { label: 'Post-application', value: summary.post_application_total || 0, detail: 'Tracked after application', icon: BriefcaseBusiness },
    { label: 'Interviewing', value: summary.interviewing || 0, detail: 'Active interview stage', icon: CalendarClock },
    { label: 'Offers', value: summary.offers || 0, detail: 'Recorded offers', icon: Trophy },
    { label: 'Follow-up attention', value: summary.followups_requiring_attention || 0, detail: 'Still governed by approval', icon: ShieldCheck },
  ], [summary])

  if (workspace.isLoading) return <div className="flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading post-application operations…</div>
  if (workspace.isError) return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{getApiErrorMessage(workspace.error, 'Could not load post-application operations')}</div>

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="section-kicker">Phase 9 · Post-application operations</p>
          <h1 className="mt-1 text-2xl font-black tracking-tight text-gray-900">Post-Application Center</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-500">Classify employer messages, confirm status changes, prepare for interviews, compare offers, and preserve outcome learning with provenance.</p>
        </div>
        <Link to="/followup-review" className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-700 shadow-sm">Follow-up Review <ArrowRight className="h-3.5 w-3.5" /></Link>
      </div>

      <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
        <div className="flex items-start gap-3"><ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-blue-700" /><div><div className="text-sm font-bold text-blue-900">Classification is not permission.</div><p className="mt-1 text-xs leading-5 text-blue-800">Inbound email classification never changes application status automatically. Recruiter follow-up sending still requires its independent exact-payload approval and outbound kill switch.</p></div></div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{metrics.map((metric) => <Metric key={metric.label} {...metric} />)}</div>

      <div className="flex gap-1 overflow-x-auto rounded-xl border border-gray-200 bg-white p-1 shadow-sm">{TABS.map(({ id, label, icon: Icon }) => <button key={id} type="button" onClick={() => setTab(id)} className={`inline-flex flex-shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs font-bold transition ${tab === id ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'}`}><Icon className="h-3.5 w-3.5" />{label}</button>)}</div>

      {tab === 'inbox' && <EmployerInbox workspace={workspace.data} refresh={() => workspace.refetch()} />}
      {tab === 'interviews' && <Interviews workspace={workspace.data} />}
      {tab === 'offers' && <OffersAndOutcomes workspace={workspace.data} />}
    </div>
  )
}
