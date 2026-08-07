import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Contact,
  Loader2,
  MailCheck,
  MailWarning,
  RefreshCw,
  Save,
  Send,
  ShieldCheck,
  ShieldOff,
} from 'lucide-react'

import {
  approveFollowup,
  createFollowup,
  getApiErrorMessage,
  getFollowupPreflight,
  listApplications,
  listFollowups,
  revokeFollowup,
  sendFollowup,
  updateFollowup,
} from '../api/client'
import { listRecruiterContacts } from '../api/intelligence'

const EDITABLE_STATUSES = new Set(['draft', 'needs_recipient', 'approved'])

function localInputValue(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function formatDate(value) {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

function statusClass(status) {
  if (status === 'sent') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'approved') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'delivery_uncertain') return 'border-red-200 bg-red-50 text-red-700'
  if (status === 'sending') return 'border-violet-200 bg-violet-50 text-violet-700'
  if (status === 'needs_recipient') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-gray-200 bg-gray-50 text-gray-600'
}

function SafetyFlag({ ok, label, detail }) {
  const Icon = ok ? CheckCircle2 : AlertTriangle
  return (
    <div className={`rounded-xl border px-3 py-3 ${ok ? 'border-emerald-100 bg-emerald-50' : 'border-amber-100 bg-amber-50'}`}>
      <div className="flex items-start gap-2">
        <Icon className={`mt-0.5 h-4 w-4 flex-shrink-0 ${ok ? 'text-emerald-700' : 'text-amber-700'}`} />
        <div>
          <div className={`text-xs font-bold ${ok ? 'text-emerald-800' : 'text-amber-900'}`}>{label}</div>
          <div className={`mt-1 text-[11px] leading-relaxed ${ok ? 'text-emerald-700' : 'text-amber-800'}`}>{detail}</div>
        </div>
      </div>
    </div>
  )
}

export default function FollowUpReview() {
  const qc = useQueryClient()
  const [applicationId, setApplicationId] = useState('')
  const [followupId, setFollowupId] = useState('')
  const [contactId, setContactId] = useState('')
  const [recipientEmail, setRecipientEmail] = useState('')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [scheduledAt, setScheduledAt] = useState('')
  const [acknowledgment, setAcknowledgment] = useState('')

  const applicationsQuery = useQuery({
    queryKey: ['applications', 'followup-review'],
    queryFn: () => listApplications({ per_page: 100 }),
    select: (response) => response.data || [],
  })
  const applications = useMemo(
    () => (applicationsQuery.data || []).filter((item) => ['applied', 'interviewing'].includes(item.status)),
    [applicationsQuery.data],
  )

  useEffect(() => {
    if (!applicationId && applications.length) setApplicationId(String(applications[0].id))
    if (applicationId && applications.length && !applications.some((item) => String(item.id) === applicationId)) {
      setApplicationId(String(applications[0].id))
    }
  }, [applications, applicationId])

  const selectedApplication = useMemo(
    () => applications.find((item) => String(item.id) === applicationId),
    [applications, applicationId],
  )

  const followupsQuery = useQuery({
    queryKey: ['followups', applicationId],
    queryFn: () => listFollowups(applicationId),
    select: (response) => response.data || [],
    enabled: Boolean(applicationId),
    refetchInterval: 10_000,
  })
  const followups = followupsQuery.data || []

  useEffect(() => {
    if (!followupId && followups.length) setFollowupId(String(followups[0].id))
    if (followupId && followups.length && !followups.some((item) => String(item.id) === followupId)) {
      setFollowupId(String(followups[0].id))
    }
    if (!followups.length) setFollowupId('')
  }, [followups, followupId])

  const selectedFollowup = useMemo(
    () => followups.find((item) => String(item.id) === followupId),
    [followups, followupId],
  )

  const contactsQuery = useQuery({
    queryKey: ['recruiter-contacts', 'followup-review', selectedApplication?.job?.company],
    queryFn: () => listRecruiterContacts({ company: selectedApplication?.job?.company || undefined }),
    select: (response) => response.data || [],
    enabled: Boolean(selectedApplication),
  })
  const contacts = contactsQuery.data || []

  const preflightQuery = useQuery({
    queryKey: ['followup-preflight', applicationId, followupId],
    queryFn: () => getFollowupPreflight(applicationId, followupId),
    select: (response) => response.data,
    enabled: Boolean(applicationId && followupId),
    refetchInterval: (query) => {
      const value = query.state.data
      return value?.status === 'sending' ? 2000 : false
    },
  })
  const preflight = preflightQuery.data

  useEffect(() => {
    if (!selectedFollowup) {
      setContactId('')
      setRecipientEmail('')
      setSubject('')
      setMessage('')
      setScheduledAt('')
      setAcknowledgment('')
      return
    }
    setContactId(selectedFollowup.recruiter_contact_id ? String(selectedFollowup.recruiter_contact_id) : '')
    setRecipientEmail(selectedFollowup.recipient_email || '')
    setSubject(selectedFollowup.subject || '')
    setMessage(selectedFollowup.message || '')
    setScheduledAt(localInputValue(selectedFollowup.scheduled_at))
    setAcknowledgment('')
  }, [selectedFollowup?.id, selectedFollowup?.updated_at, selectedFollowup?.approval_status])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['followups', applicationId] })
    qc.invalidateQueries({ queryKey: ['followup-preflight', applicationId, followupId] })
    qc.invalidateQueries({ queryKey: ['application', applicationId] })
    qc.invalidateQueries({ queryKey: ['applications'] })
    qc.invalidateQueries({ queryKey: ['recruiter-contacts'] })
  }

  const createMutation = useMutation({
    mutationFn: () => {
      const job = selectedApplication?.job
      const when = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000)
      return createFollowup(applicationId, {
        scheduled_at: when.toISOString(),
        subject: `Following up on my ${job?.title || 'application'} application at ${job?.company || 'your company'}`,
        message: `Dear Hiring Team,\n\nI’m following up on my application for the ${job?.title || 'position'} at ${job?.company || 'your company'}. I remain interested in the opportunity and would appreciate any update on next steps.\n\nPlease let me know if I can provide any additional information.\n\nBest regards,`,
      })
    },
    onSuccess: (response) => {
      const id = response.data?.id
      toast.success('Follow-up draft created. No outreach has been authorized.')
      qc.invalidateQueries({ queryKey: ['followups', applicationId] })
      if (id) setFollowupId(String(id))
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not create follow-up draft')),
  })

  const saveMutation = useMutation({
    mutationFn: () => updateFollowup(applicationId, followupId, {
      recruiter_contact_id: contactId ? Number(contactId) : null,
      recipient_email: recipientEmail || null,
      subject,
      message,
      scheduled_at: new Date(scheduledAt).toISOString(),
    }),
    onSuccess: () => {
      toast.success('Draft saved. Any prior outreach approval was revoked.')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not save follow-up draft')),
  })

  const approveMutation = useMutation({
    mutationFn: () => approveFollowup(applicationId, followupId, acknowledgment),
    onSuccess: () => {
      toast.success('Exact follow-up payload approved. Application submission permission is unchanged.')
      setAcknowledgment('')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Follow-up approval failed')),
  })

  const revokeMutation = useMutation({
    mutationFn: () => revokeFollowup(applicationId, followupId, 'Revoked from Follow-up Review workspace'),
    onSuccess: () => {
      toast.success('Follow-up approval revoked.')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not revoke follow-up approval')),
  })

  const sendMutation = useMutation({
    mutationFn: () => sendFollowup(applicationId, followupId),
    onSuccess: () => {
      toast.success('Approved follow-up queued for supervised delivery.')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Follow-up could not be queued')),
  })

  const selectedContact = contacts.find((item) => String(item.id) === contactId)
  const editable = Boolean(selectedFollowup && EDITABLE_STATUSES.has(selectedFollowup.status))
  const dirty = Boolean(selectedFollowup && (
    String(selectedFollowup.recruiter_contact_id || '') !== contactId
    || (selectedFollowup.recipient_email || '') !== recipientEmail
    || (selectedFollowup.subject || '') !== subject
    || (selectedFollowup.message || '') !== message
    || localInputValue(selectedFollowup.scheduled_at) !== scheduledAt
  ))
  const expected = preflight?.expected_acknowledgment || ''
  const approvalPhraseReady = acknowledgment === expected
  const busy = createMutation.isPending
    || saveMutation.isPending
    || approveMutation.isPending
    || revokeMutation.isPending
    || sendMutation.isPending

  const handleContactChange = (value) => {
    setContactId(value)
    const contact = contacts.find((item) => String(item.id) === value)
    setRecipientEmail(contact?.email || '')
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <header>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-tomato-600">
          <MailCheck className="h-4 w-4" />
          Supervised communication
        </div>
        <h1 className="mt-2 text-xl font-bold text-gray-900 md:text-2xl">Follow-up Review</h1>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-gray-600">
          Prepare and approve recruiter follow-ups without turning application approval into outreach consent. Every send is bound to one exact recipient, message, schedule, and payload hash.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <section className="card p-4">
            <label className="text-xs font-bold uppercase tracking-wide text-gray-500">Application</label>
            <select
              value={applicationId}
              onChange={(event) => {
                setApplicationId(event.target.value)
                setFollowupId('')
              }}
              className="input mt-2 w-full"
            >
              {applications.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.job?.title || 'Application'} · {item.job?.company || 'Unknown company'}
                </option>
              ))}
            </select>
            {!applications.length && !applicationsQuery.isLoading && (
              <div className="mt-3 text-xs text-gray-500">No applied or interviewing applications are available.</div>
            )}
          </section>

          <section className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-gray-100 p-4">
              <div>
                <div className="text-sm font-bold text-gray-900">Drafts</div>
                <div className="mt-0.5 text-xs text-gray-500">Nothing here can send without approval.</div>
              </div>
              <button
                type="button"
                onClick={() => createMutation.mutate()}
                disabled={!applicationId || busy}
                className="btn-secondary px-3 py-2 text-xs"
              >
                New draft
              </button>
            </div>
            <div className="divide-y divide-gray-100">
              {followups.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => setFollowupId(String(item.id))}
                  className={`w-full p-4 text-left ${String(item.id) === followupId ? 'bg-blue-50/70' : 'hover:bg-gray-50'}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-gray-900">{item.subject || `Follow-up #${item.id}`}</div>
                      <div className="mt-1 truncate text-xs text-gray-500">{item.recipient_email || 'Recipient not selected'}</div>
                    </div>
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${statusClass(item.status)}`}>
                      {item.status.replaceAll('_', ' ')}
                    </span>
                  </div>
                  <div className="mt-2 text-[11px] text-gray-400">{formatDate(item.scheduled_at)}</div>
                </button>
              ))}
              {!followups.length && !followupsQuery.isLoading && (
                <div className="p-5 text-center text-xs text-gray-500">No follow-up drafts yet.</div>
              )}
            </div>
          </section>
        </aside>

        <main className="space-y-4">
          {!selectedFollowup ? (
            <section className="card p-8 text-center">
              <MailWarning className="mx-auto h-8 w-8 text-gray-300" />
              <div className="mt-3 text-sm font-semibold text-gray-700">Choose or create a follow-up draft.</div>
            </section>
          ) : (
            <>
              <section className="card p-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <Contact className="h-5 w-5 text-slate-600" />
                      <h2 className="font-bold text-gray-900">Exact recipient & message</h2>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-gray-500">
                      The recruiter contact must belong to this account and match the application company. Saving any edit revokes prior approval.
                    </p>
                  </div>
                  <span className={`self-start rounded-full border px-2.5 py-1 text-xs font-bold ${statusClass(selectedFollowup.status)}`}>
                    {selectedFollowup.status.replaceAll('_', ' ')}
                  </span>
                </div>

                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                  <label className="text-sm font-medium text-gray-700">
                    Recruiter contact
                    <select
                      value={contactId}
                      onChange={(event) => handleContactChange(event.target.value)}
                      disabled={!editable}
                      className="input mt-1.5 w-full"
                    >
                      <option value="">Select verified contact</option>
                      {contacts.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.full_name} · {item.company}{item.email ? ` · ${item.email}` : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-medium text-gray-700">
                    Recipient email
                    <input
                      value={recipientEmail}
                      onChange={(event) => setRecipientEmail(event.target.value)}
                      disabled={!editable}
                      className="input mt-1.5 w-full"
                      placeholder="Select a recruiter contact"
                    />
                  </label>
                </div>

                {selectedContact && (
                  <div className="mt-3 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-600">
                    Selected identity: <strong>{selectedContact.full_name}</strong> · {selectedContact.title || 'Recruiter'} · {selectedContact.company}
                  </div>
                )}

                <label className="mt-4 block text-sm font-medium text-gray-700">
                  Schedule
                  <input
                    type="datetime-local"
                    value={scheduledAt}
                    onChange={(event) => setScheduledAt(event.target.value)}
                    disabled={!editable}
                    className="input mt-1.5 w-full"
                  />
                </label>
                <label className="mt-4 block text-sm font-medium text-gray-700">
                  Subject
                  <input
                    value={subject}
                    onChange={(event) => setSubject(event.target.value)}
                    disabled={!editable}
                    className="input mt-1.5 w-full"
                  />
                </label>
                <label className="mt-4 block text-sm font-medium text-gray-700">
                  Message
                  <textarea
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    disabled={!editable}
                    rows={9}
                    className="input mt-1.5 w-full resize-y"
                  />
                </label>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => saveMutation.mutate()}
                    disabled={!editable || !dirty || !scheduledAt || !subject.trim() || !message.trim() || busy}
                    className="btn-secondary inline-flex items-center gap-2"
                  >
                    {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    Save exact draft
                  </button>
                  <button
                    type="button"
                    onClick={() => preflightQuery.refetch()}
                    disabled={preflightQuery.isFetching}
                    className="btn-secondary inline-flex items-center gap-2"
                  >
                    <RefreshCw className={`h-4 w-4 ${preflightQuery.isFetching ? 'animate-spin' : ''}`} />
                    Refresh preflight
                  </button>
                </div>
              </section>

              <section className="card p-5">
                <div className="flex items-start gap-3">
                  <ShieldCheck className="mt-0.5 h-5 w-5 text-blue-700" />
                  <div>
                    <h2 className="font-bold text-gray-900">Independent outreach approval</h2>
                    <p className="mt-1 text-xs leading-relaxed text-gray-500">
                      Application submission approval does not authorize recruiter outreach. This approval binds only this recipient, subject, message, schedule, and idempotency key.
                    </p>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <SafetyFlag
                    ok={Boolean(preflight?.eligible_for_approval)}
                    label="Payload eligible"
                    detail={preflight?.eligible_for_approval ? 'Recipient and message identity are complete.' : 'Resolve blockers before approval.'}
                  />
                  <SafetyFlag
                    ok={Boolean(preflight?.approval_active)}
                    label="Exact approval"
                    detail={preflight?.approval_active ? 'Current hash matches the approved payload.' : 'No active approval for this exact payload.'}
                  />
                  <SafetyFlag
                    ok={Boolean(preflight?.provider_configured)}
                    label="Email provider"
                    detail={preflight?.provider_configured ? 'Real provider credentials are configured.' : 'Provider is not configured. Mock mode cannot send recruiter email.'}
                  />
                  <SafetyFlag
                    ok={Boolean(preflight?.global_send_enabled)}
                    label="Outbound kill switch"
                    detail={preflight?.global_send_enabled ? 'Real follow-up sending is enabled.' : 'ALLOW_REAL_FOLLOWUP_SEND remains off.'}
                  />
                </div>

                {preflight?.blockers?.length > 0 && (
                  <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <div className="text-xs font-bold uppercase tracking-wide text-amber-800">Current blockers</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {preflight.blockers.map((item) => (
                        <span key={item} className="rounded-full border border-amber-200 bg-white px-2 py-1 text-[11px] font-semibold text-amber-800">
                          {item.replaceAll('_', ' ')}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {expected && !preflight?.approval_active && (
                  <div className="mt-4">
                    <label className="text-sm font-medium text-gray-700">
                      Type the exact approval phrase
                      <code className="mt-1.5 block break-all rounded-lg bg-slate-950 px-3 py-2 text-xs text-slate-100">{expected}</code>
                      <input
                        value={acknowledgment}
                        onChange={(event) => setAcknowledgment(event.target.value)}
                        className="input mt-2 w-full"
                        placeholder={expected}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => approveMutation.mutate()}
                      disabled={!approvalPhraseReady || !preflight?.eligible_for_approval || dirty || busy}
                      className="btn-primary mt-3 inline-flex items-center gap-2"
                    >
                      {approveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                      Approve exact follow-up
                    </button>
                  </div>
                )}

                {preflight?.approval_active && (
                  <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-bold text-blue-900">Approval active</div>
                        <div className="mt-1 text-xs text-blue-700">Expires {formatDate(preflight.approval_expires_at)}</div>
                        <div className="mt-2 break-all font-mono text-[10px] text-blue-600">{preflight.payload_hash}</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => revokeMutation.mutate()}
                        disabled={busy}
                        className="btn-secondary inline-flex items-center gap-2 text-xs"
                      >
                        <ShieldOff className="h-4 w-4" /> Revoke
                      </button>
                    </div>
                  </div>
                )}
              </section>

              <section className="card p-5">
                <div className="flex items-start gap-3">
                  <CalendarClock className="mt-0.5 h-5 w-5 text-slate-600" />
                  <div className="flex-1">
                    <h2 className="font-bold text-gray-900">Delivery</h2>
                    <p className="mt-1 text-xs leading-relaxed text-gray-500">
                      Due approved messages may be picked up by the hourly worker. Manual queueing is available only when the exact approval, due time, provider, and outbound switch all pass.
                    </p>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                    <div className="text-[11px] font-bold uppercase tracking-wide text-gray-400">Scheduled</div>
                    <div className="mt-1 text-sm font-semibold text-gray-800">{formatDate(preflight?.scheduled_at)}</div>
                  </div>
                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                    <div className="text-[11px] font-bold uppercase tracking-wide text-gray-400">Attempts</div>
                    <div className="mt-1 text-sm font-semibold text-gray-800">{preflight?.send_attempt_count || 0}</div>
                  </div>
                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                    <div className="text-[11px] font-bold uppercase tracking-wide text-gray-400">Last delivery</div>
                    <div className="mt-1 text-sm font-semibold text-gray-800">{formatDate(preflight?.sent_at)}</div>
                  </div>
                </div>

                {selectedFollowup.status === 'delivery_uncertain' && (
                  <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                    Provider outcome is uncertain. Automatic retry is disabled. Review the provider state before creating a new approval.
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => sendMutation.mutate()}
                  disabled={!preflight?.ready_for_delivery || dirty || busy}
                  className="btn-primary mt-4 inline-flex items-center gap-2"
                >
                  {sendMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : preflight?.due ? <Send className="h-4 w-4" /> : <Clock3 className="h-4 w-4" />}
                  Queue approved delivery
                </button>
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  )
}
