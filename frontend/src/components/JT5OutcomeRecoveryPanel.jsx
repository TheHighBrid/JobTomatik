import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { getJT5Reconciliation, reconcileJT5Outcome, getApiErrorMessage } from '../api/client'

export default function JT5OutcomeRecoveryPanel({ application }) {
  const qc = useQueryClient()
  const [outcome, setOutcome] = useState('')
  const [evidenceId, setEvidenceId] = useState('')
  const [source, setSource] = useState('')
  const [reference, setReference] = useState('')
  const [notes, setNotes] = useState('')
  const [verified, setVerified] = useState(false)
  const context = useQuery({
    queryKey: ['jt5-reconciliation', application.id],
    queryFn: () => getJT5Reconciliation(application.id),
    select: (response) => response.data,
    retry: false,
  })
  const evidence = context.data?.confirmation_evidence || []
  const selected = evidence.find((item) => String(item.id) === evidenceId)
  const canRecordNonSubmission = ['pending', 'applying'].includes(application.status)

  useEffect(() => {
    setVerified(false)
  }, [outcome, evidenceId, selected?.snapshot_hash, source, reference, notes])

  const resolution = useMutation({
    mutationFn: () => reconcileJT5Outcome(application.id, {
      attempt_reference: context.data.attempt_reference,
      outcome,
      evidence_source: outcome === 'confirmed' ? 'retained_confirmation' : source,
      evidence_reference: outcome === 'confirmed' ? `submission-evidence:${selected.id}` : reference.trim(),
      notes: notes.trim(),
      outcome_verified: verified,
      evidence_id: outcome === 'confirmed' ? selected.id : null,
      evidence_snapshot_hash: outcome === 'confirmed' ? selected.snapshot_hash : null,
    }),
    retry: false,
    onSuccess: async () => {
      toast.success(outcome === 'confirmed'
        ? 'Submission outcome recorded from the retained evidence.'
        : 'Non-submission recorded. A new attempt still requires Apply.')
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['application', String(application.id)] }),
        qc.invalidateQueries({ queryKey: ['application', application.id] }),
        qc.invalidateQueries({ queryKey: ['jt5-application-status', String(application.id)] }),
        qc.invalidateQueries({ queryKey: ['jt5-reconciliation', application.id] }),
        qc.invalidateQueries({ queryKey: ['applications'] }),
      ])
    },
    onError: (error) => {
      setVerified(false)
      toast.error(getApiErrorMessage(error, 'The outcome could not be recorded. The retry block is preserved.'))
      qc.invalidateQueries({ queryKey: ['jt5-reconciliation', application.id] })
    },
  })

  const sourceReady = outcome === 'confirmed'
    ? Boolean(selected)
    : outcome === 'not_submitted' && canRecordNonSubmission && Boolean(source && reference.trim())
  const canSave = context.data?.resolution_required && !context.isError && !context.isFetching
    && sourceReady && notes.trim().length >= 20 && verified && !resolution.isPending

  return (
    <section className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      <h3 className="flex items-center gap-2 font-semibold"><AlertCircle className="h-4 w-4" /> Resolve the prior outcome</h3>
      <p className="mt-2">The prior attempt needs reconciliation. JobTomatik will not start another attempt automatically.</p>
      <p className="mt-2">Use retained confirmation or an authoritative employer verification. A missing email or an unanswered application does not establish non-submission.</p>
      {context.isPending && <p role="status" className="mt-3">Loading retained outcome evidence…</p>}
      {context.isError && (
        <div role="alert" className="mt-3">
          Recovery evidence could not be loaded.
          <button type="button" className="ml-2 underline" onClick={() => context.refetch()}>Refresh recovery evidence</button>
        </div>
      )}
      {context.data?.resolution_required && (
        <form className="mt-4 space-y-3" onSubmit={(event) => { event.preventDefault(); if (canSave) resolution.mutate() }}>
          <label className="block">Verified outcome
            <select className="input mt-1" value={outcome} onChange={(event) => setOutcome(event.target.value)}>
              <option value="">Outcome remains unknown</option>
              <option value="confirmed" disabled={!evidence.length}>Submission confirmed by retained evidence</option>
              <option value="not_submitted" disabled={!canRecordNonSubmission}>Employer verified no submission</option>
            </select>
          </label>
          {!evidence.length && <p>No sufficient confirmation evidence is retained for this attempt. Keep the outcome unknown unless authoritative employer verification establishes non-submission.</p>}
          {!canRecordNonSubmission && <p>Recorded application history cannot be reset here. Confirmation can be recorded when sufficient evidence is available.</p>}
          {outcome === 'confirmed' && (
            <>
              <label className="block">Retained confirmation
                <select className="input mt-1" value={evidenceId} onChange={(event) => setEvidenceId(event.target.value)}>
                  <option value="">Select evidence to review</option>
                  {evidence.map((item) => <option key={item.id} value={item.id}>#{item.id} · {item.evidence_type}</option>)}
                </select>
              </label>
              {selected && (
                <div className="rounded border border-amber-200 bg-white p-3 break-words">
                  <p className="whitespace-pre-wrap">{selected.confirmation_text || selected.external_application_id}</p>
                  <p className="mt-2 text-xs">{selected.final_url}</p>
                </div>
              )}
            </>
          )}
          {outcome === 'not_submitted' && (
            <>
              <label className="block">Verification source
                <select className="input mt-1" value={source} onChange={(event) => setSource(event.target.value)}>
                  <option value="">Select an authoritative source</option>
                  <option value="employer_response">Employer response</option>
                  <option value="employer_portal">Employer portal verification</option>
                </select>
              </label>
              <label className="block">Evidence reference
                <input className="input mt-1" value={reference} maxLength={1000} onChange={(event) => setReference(event.target.value)} placeholder="Case number or portal verification reference" />
              </label>
            </>
          )}
          {outcome && (
            <>
              <label className="block">What did the evidence establish?
                <textarea className="input mt-1" value={notes} minLength={20} maxLength={4000} onChange={(event) => setNotes(event.target.value)} placeholder="Describe the evidence for this exact employer, role and application." />
              </label>
              <label className="flex items-start gap-2">
                <input type="checkbox" className="mt-1" checked={verified} onChange={(event) => setVerified(event.target.checked)} />
                I reviewed the evidence and verified this outcome for this exact application.
              </label>
              <button type="submit" className="btn-primary flex w-full items-center justify-center gap-2" disabled={!canSave}>
                {resolution.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Record verified outcome
              </button>
            </>
          )}
        </form>
      )}
      {context.data && !context.data.resolution_required && <p className="mt-3">This attempt no longer requires recovery. Refresh the application to see its saved status.</p>}
    </section>
  )
}
