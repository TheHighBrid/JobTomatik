import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { getJT5Reconciliation, reconcileJT5Outcome, getApiErrorMessage } from '../api/client'

function useRecoveryForm() {
  const [evidenceId, setEvidenceId] = useState('')
  const [notes, setNotes] = useState('')
  const [verified, setVerified] = useState(false)
  return { evidenceId, setEvidenceId, notes, setNotes, verified, setVerified }
}

function reviewPayload(context, selected, form) {
  return {
    attempt_reference: context.data.attempt_reference, outcome: 'confirmed',
    evidence_source: 'retained_confirmation', evidence_reference: `submission-evidence:${selected.id}`,
    notes: form.notes.trim(), outcome_verified: form.verified,
    evidence_id: selected.id, evidence_snapshot_hash: selected.snapshot_hash,
  }
}

function useRecoveryMutation(id, context, selected, form) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => reconcileJT5Outcome(id, reviewPayload(context, selected, form)),
    retry: false,
    onSuccess: async () => {
      form.setVerified(false)
      toast.success('Submission outcome recorded from the retained evidence.')
      const keys = [['application', String(id)], ['application', id], ['applications'],
        ['jt5-application-status', String(id)], ['jt5-reconciliation', id],
        ['submission-evidence-reviews', Number(id)],
        ['submission-evidence-review-preflight', Number(id)]]
      await Promise.all(keys.map((queryKey) => qc.invalidateQueries({ queryKey })))
    },
    onError: (error) => {
      form.setVerified(false)
      toast.error(getApiErrorMessage(error, 'The outcome could not be recorded. The retry block is preserved.'))
      qc.invalidateQueries({ queryKey: ['jt5-reconciliation', id] })
    },
  })
}

function readableConfirmation(selected) {
  return selected.confirmation_text?.trim() || selected.external_application_id?.trim()
}

function canRecord(context, selected, form, pending) {
  return Boolean(context.data?.resolution_available && !context.isError && !context.isFetching
    && selected && form.notes.trim().length >= 20 && form.verified && !pending)
}

function RecoveryForm({ context, selected, form, resolution }) {
  const evidence = context.data.confirmation_evidence
  const canSave = canRecord(context, selected, form, resolution.isPending)
  return (
    <form className="mt-4 space-y-3" onSubmit={(event) => { event.preventDefault(); if (canSave) resolution.mutate() }}>
      <label className="block">Retained confirmation
        <select className="input mt-1" value={form.evidenceId} onChange={(event) => form.setEvidenceId(event.target.value)}>
          <option value="">Select evidence to review</option>
          {evidence.map((item) => <option key={item.id} value={item.id}>#{item.id} · {item.evidence_type}</option>)}
        </select>
      </label>
      {selected && <div className="rounded border border-amber-200 bg-white p-3 break-words">
        <p className="whitespace-pre-wrap">{readableConfirmation(selected)}</p>
        <p className="mt-2 text-xs">{selected.final_url}</p>
      </div>}
      <label className="block">What did the evidence establish?
        <textarea className="input mt-1" value={form.notes} minLength={20} maxLength={4000}
          onChange={(event) => form.setNotes(event.target.value)} placeholder="Describe the evidence for this exact employer, role and application." />
      </label>
      <label className="flex items-start gap-2">
        <input type="checkbox" className="mt-1" checked={form.verified} onChange={(event) => form.setVerified(event.target.checked)} />
        I reviewed the evidence and verified this outcome for this exact application.
      </label>
      <button type="submit" className="btn-primary flex w-full items-center justify-center gap-2" disabled={!canSave}>
        {resolution.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Record verified outcome
      </button>
    </form>
  )
}

function RecoveryStatus({ context }) {
  if (context.isPending) return <p role="status" className="mt-3">Loading retained outcome evidence…</p>
  if (context.isError) return <div role="alert" className="mt-3">Recovery evidence could not be loaded.
    <button type="button" className="ml-2 underline" onClick={() => context.refetch()}>Refresh recovery evidence</button>
  </div>
  if (!context.data.resolution_required) return <p className="mt-3">This attempt no longer requires recovery. Refresh the application to see its saved status.</p>
  if (context.data.resolution_available) return null
  return <div role="status" className="mt-3">
    <p>Recovery is unavailable. The outcome stays unknown and another attempt stays blocked.</p>
    {context.data.blockers?.map((blocker) => <p key={blocker}>{blocker}</p>)}
  </div>
}

export default function JT5OutcomeRecoveryPanel({ application }) {
  const form = useRecoveryForm()
  const context = useQuery({
    queryKey: ['jt5-reconciliation', application.id],
    queryFn: () => getJT5Reconciliation(application.id),
    select: (response) => response.data, retry: false,
  })
  const data = context.data || {}
  const evidence = data.confirmation_evidence || []
  const selected = evidence.find((item) => String(item.id) === form.evidenceId)
  const resolution = useRecoveryMutation(application.id, context, selected, form)
  useEffect(() => { form.setVerified(false) },
    [form.evidenceId, form.notes, selected?.snapshot_hash, data.attempt_reference, data.resolution_available])
  return (
    <section className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      <h3 className="flex items-center gap-2 font-semibold"><AlertCircle className="h-4 w-4" /> Resolve the prior outcome</h3>
      <p className="mt-2">The prior attempt needs reconciliation. JobTomatik will not start another attempt automatically.</p>
      <p className="mt-2">Review the saved confirmation below. Notes or a missing email cannot unlock another attempt. Close any active handoff before recording confirmation.</p>
      <RecoveryStatus context={context} />
      {data.resolution_available && !context.isError && (
        <RecoveryForm context={context} selected={selected} form={form} resolution={resolution} />
      )}
    </section>
  )
}
