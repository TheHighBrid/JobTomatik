import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileCheck2,
  Fingerprint,
  Gauge,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldCheck,
  TimerReset,
  XCircle,
} from 'lucide-react'

import { getApiErrorMessage } from '../api/client'
import {
  authorizeCertificationTrack,
  getCertificationEvidence,
  getCertificationManifest,
  recordCertificationEvidence,
  revokeCertificationAuthorization,
  verifyCertificationEvidence,
} from '../api/certification'

const EVIDENCE_TYPES = [
  'supervised_real_submission',
  'zero_false_submission_audit',
  'duplicate_prevention',
  'confirmation_evidence',
  'recovery_incident_drill',
  'handoff_notifications',
  'policy_controls',
  'monitoring_alerting',
  'autonomous_pilot',
  'android_device_acceptance',
  'release_artifact',
  'release_checksum',
]

function humanize(value) {
  return String(value || '').replaceAll('_', ' ')
}

function shortSha(value) {
  return String(value || '').slice(0, 12) || 'unknown'
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

function Card({ children, className = '' }) {
  return <div className={`rounded-2xl border border-gray-200 bg-white p-4 shadow-sm ${className}`}>{children}</div>
}

function StatusPill({ ok, children }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-bold ${
      ok
        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
        : 'border-amber-200 bg-amber-50 text-amber-700'
    }`}>
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
      {children}
    </span>
  )
}

function RuntimeControl({ label, value, safeWhenFalse = false }) {
  const safe = safeWhenFalse ? !value : Boolean(value)
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
      <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-gray-400">{label}</div>
      <div className={`mt-1 text-sm font-black ${safe ? 'text-emerald-700' : 'text-amber-700'}`}>
        {String(Boolean(value)).toUpperCase()}
      </div>
    </div>
  )
}

function TrackCard({ track }) {
  const entries = Object.entries(track?.evidence || {})
  return (
    <Card className="h-full">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-[0.12em] text-gray-400">{humanize(track.scope)}</div>
          <div className="mt-1 text-lg font-black text-gray-900">{track.release_version}</div>
        </div>
        <StatusPill ok={track.ready}>{track.ready ? 'Ready' : `${track.blockers?.length || 0} blockers`}</StatusPill>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-xl bg-gray-50 p-3"><div className="text-gray-400">Prerequisites</div><div className="mt-1 font-bold text-gray-900">{track.prerequisites_ready ? 'Complete' : 'Incomplete'}</div></div>
        <div className="rounded-xl bg-gray-50 p-3"><div className="text-gray-400">Owner authorization</div><div className="mt-1 font-bold text-gray-900">{track.owner_authorized ? 'Active' : 'Missing'}</div></div>
      </div>
      <div className="mt-4 space-y-2">
        {entries.map(([name, gate]) => (
          <div key={name} className="rounded-xl border border-gray-100 px-3 py-2.5">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0 text-xs font-semibold text-gray-800">{humanize(name)}</div>
              {gate.qualifying ? <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-emerald-600" /> : <XCircle className="h-4 w-4 flex-shrink-0 text-gray-300" />}
            </div>
            {!gate.qualifying && <div className="mt-1 truncate text-[10px] text-gray-400">{(gate.reasons || []).join(', ')}</div>}
          </div>
        ))}
      </div>
    </Card>
  )
}

function EvidenceLedger({ manifest, evidence }) {
  const queryClient = useQueryClient()
  const [recordForm, setRecordForm] = useState({
    evidenceType: 'recovery_incident_drill',
    environment: 'production-like',
    status: 'passed',
    durationSeconds: '',
    sourceReference: '',
    metadata: '{}',
  })
  const [verifyTarget, setVerifyTarget] = useState(null)
  const [verifyAck, setVerifyAck] = useState('')
  const [verifyReference, setVerifyReference] = useState('')
  const [error, setError] = useState('')

  const record = useMutation({
    mutationFn: () => {
      let parsed = {}
      try {
        parsed = JSON.parse(recordForm.metadata || '{}')
      } catch {
        throw new Error('Evidence metadata must be valid JSON')
      }
      return recordCertificationEvidence({
        evidence_type: recordForm.evidenceType,
        commit_sha: manifest.candidate_revision,
        environment: recordForm.environment,
        status: recordForm.status,
        duration_seconds: recordForm.durationSeconds ? Number(recordForm.durationSeconds) : null,
        source_reference: recordForm.sourceReference,
        evidence_metadata: parsed,
      })
    },
    onSuccess: () => {
      setError('')
      setRecordForm((current) => ({ ...current, sourceReference: '', durationSeconds: '', metadata: '{}' }))
      queryClient.invalidateQueries({ queryKey: ['certification-evidence'] })
      queryClient.invalidateQueries({ queryKey: ['certification-manifest'] })
    },
    onError: (err) => setError(getApiErrorMessage(err, err?.message || 'Could not record evidence')),
  })

  const verify = useMutation({
    mutationFn: () => verifyCertificationEvidence(verifyTarget.evidence_id, {
      acknowledgment: verifyAck,
      review_reference: verifyReference,
    }),
    onSuccess: () => {
      setError('')
      setVerifyTarget(null)
      setVerifyAck('')
      setVerifyReference('')
      queryClient.invalidateQueries({ queryKey: ['certification-evidence'] })
      queryClient.invalidateQueries({ queryKey: ['certification-manifest'] })
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not verify evidence')),
  })

  const expectedAck = verifyTarget
    ? `VERIFY EVIDENCE ${verifyTarget.evidence_id} ${shortSha(verifyTarget.commit_sha)}`
    : ''

  return (
    <div className="grid gap-4 xl:grid-cols-[0.9fr_1.4fr]">
      <Card>
        <div className="flex items-center gap-2"><FileCheck2 className="h-4 w-4 text-blue-600" /><h2 className="text-sm font-bold text-gray-900">Record retained evidence</h2></div>
        <p className="mt-2 text-xs leading-5 text-gray-500">Recording evidence does not certify it and never enables submission. The current candidate commit is fixed by the runtime.</p>
        <div className="mt-3 rounded-xl border border-violet-200 bg-violet-50 p-3 text-[11px] leading-5 text-violet-800">
          <strong>Shadow evidence has a dedicated provenance path.</strong> 4h, 8h, and 24h shadow records cannot be entered here. Run a qualifying full-stack campaign and record its evidence in <a href="/shadow-campaigns" className="font-bold underline">Shadow Campaigns</a>, then return here for independent review.
        </div>
        <div className="mt-4 space-y-3">
          <label className="block text-xs font-semibold text-gray-700">Evidence type<select value={recordForm.evidenceType} onChange={(event) => setRecordForm((current) => ({ ...current, evidenceType: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm">{EVIDENCE_TYPES.map((item) => <option key={item} value={item}>{humanize(item)}</option>)}</select></label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-semibold text-gray-700">Environment<input value={recordForm.environment} onChange={(event) => setRecordForm((current) => ({ ...current, environment: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" /></label>
            <label className="text-xs font-semibold text-gray-700">Status<select value={recordForm.status} onChange={(event) => setRecordForm((current) => ({ ...current, status: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm"><option value="passed">Passed</option><option value="failed">Failed</option></select></label>
          </div>
          <label className="block text-xs font-semibold text-gray-700">Measured duration seconds<input type="number" min="0" value={recordForm.durationSeconds} onChange={(event) => setRecordForm((current) => ({ ...current, durationSeconds: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" placeholder="Optional when this evidence type has a measured duration" /></label>
          <label className="block text-xs font-semibold text-gray-700">Source reference<input value={recordForm.sourceReference} onChange={(event) => setRecordForm((current) => ({ ...current, sourceReference: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" placeholder="workflow run, report, application evidence, artifact…" /></label>
          <label className="block text-xs font-semibold text-gray-700">Evidence metadata JSON<textarea rows={7} value={recordForm.metadata} onChange={(event) => setRecordForm((current) => ({ ...current, metadata: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 font-mono text-xs" /></label>
          <div className="rounded-xl bg-gray-50 p-3 text-[11px] text-gray-500">Candidate head: <code className="font-semibold text-gray-800">{manifest.candidate_revision}</code></div>
          <button type="button" disabled={record.isPending || !recordForm.sourceReference || !manifest.candidate_revision_known} onClick={() => record.mutate()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50">{record.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />} Record unreviewed evidence</button>
        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between gap-3"><div><h2 className="text-sm font-bold text-gray-900">Evidence ledger</h2><p className="mt-1 text-xs text-gray-500">Exact-head, hash-bound, reviewable records.</p></div><ClipboardCheck className="h-5 w-5 text-gray-400" /></div>
        {error && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        <div className="mt-4 space-y-2.5">
          {evidence.map((item) => (
            <div key={item.evidence_id} className="rounded-xl border border-gray-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div><div className="text-sm font-semibold text-gray-900">{humanize(item.evidence_type)}</div><div className="mt-0.5 text-[10px] text-gray-400">{shortSha(item.commit_sha)} · {item.environment} · {item.source_reference}</div></div>
                <StatusPill ok={item.review_status === 'verified'}>{item.review_status}</StatusPill>
              </div>
              <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-gray-500"><span>Status: {item.status}</span><span>Hash: {shortSha(item.payload_hash)}</span>{item.duration_seconds != null && <span>Duration: {item.duration_seconds}s</span>}<span>{formatDate(item.created_at)}</span></div>
              {item.review_status !== 'verified' && (
                <button type="button" onClick={() => { setVerifyTarget(item); setVerifyAck(''); setVerifyReference('') }} className="mt-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-[11px] font-bold text-blue-700">Review evidence</button>
              )}
            </div>
          ))}
          {!evidence.length && <div className="rounded-xl border border-dashed border-gray-300 p-8 text-center text-sm text-gray-400">No retained certification evidence yet.</div>}
        </div>

        {verifyTarget && (
          <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-3">
            <div className="text-xs font-bold text-blue-900">Verification is a separate decision</div>
            <p className="mt-1 text-[11px] leading-5 text-blue-800">Check the source artifact and payload hash first. Shadow evidence also revalidates its linked full-stack campaign before and after review. Type the exact phrase below. Verification still does not enable submission.</p>
            <code className="mt-2 block overflow-x-auto rounded-lg bg-white px-2.5 py-2 text-[11px] text-gray-800">{expectedAck}</code>
            <input value={verifyAck} onChange={(event) => setVerifyAck(event.target.value)} className="mt-2 w-full rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs" placeholder="Exact verification phrase" />
            <input value={verifyReference} onChange={(event) => setVerifyReference(event.target.value)} className="mt-2 w-full rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs" placeholder="Review reference" />
            <div className="mt-2 flex gap-2"><button type="button" disabled={verify.isPending || verifyAck !== expectedAck || !verifyReference} onClick={() => verify.mutate()} className="rounded-lg bg-blue-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">Verify retained evidence</button><button type="button" onClick={() => setVerifyTarget(null)} className="rounded-lg px-3 py-2 text-xs font-bold text-blue-700">Cancel</button></div>
          </div>
        )}
      </Card>
    </div>
  )
}

function AuthorizationPanel({ manifest }) {
  const queryClient = useQueryClient()
  const [scope, setScope] = useState('autonomous_pilot')
  const [reference, setReference] = useState('')
  const [ack, setAck] = useState('')
  const [revokeAck, setRevokeAck] = useState('')
  const [revokeReason, setRevokeReason] = useState('')
  const [error, setError] = useState('')
  const track = manifest.tracks?.[scope]
  const expected = `AUTHORIZE ${scope.toUpperCase()} ${manifest.release_version} ${shortSha(manifest.candidate_revision)}`

  const authorize = useMutation({
    mutationFn: () => authorizeCertificationTrack({
      scope,
      release_version: manifest.release_version,
      commit_sha: manifest.candidate_revision,
      approval_reference: reference,
      acknowledgment: ack,
    }),
    onSuccess: () => {
      setError('')
      setAck('')
      setReference('')
      queryClient.invalidateQueries({ queryKey: ['certification-manifest'] })
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not authorize release track')),
  })

  const authorization = track?.authorization
  const revokeExpected = authorization ? `REVOKE AUTHORIZATION ${authorization.authorization_id}` : ''
  const revoke = useMutation({
    mutationFn: () => revokeCertificationAuthorization(authorization.authorization_id, {
      acknowledgment: revokeAck,
      reason: revokeReason,
    }),
    onSuccess: () => {
      setError('')
      setRevokeAck('')
      setRevokeReason('')
      queryClient.invalidateQueries({ queryKey: ['certification-manifest'] })
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not revoke authorization')),
  })

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_1.15fr]">
      <Card>
        <div className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-violet-600" /><h2 className="text-sm font-bold text-gray-900">Owner authorization</h2></div>
        <p className="mt-2 text-xs leading-5 text-gray-500">Authorization is commit-bound, expiring, and revocable. It records the owner gate only. It does not enable real submission or autopilot.</p>
        <label className="mt-4 block text-xs font-semibold text-gray-700">Track<select value={scope} onChange={(event) => { setScope(event.target.value); setAck('') }} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm"><option value="autonomous_pilot">Autonomous pilot</option><option value="v2_release">v2.00 release</option></select></label>
        <div className="mt-3 rounded-xl bg-gray-50 p-3 text-xs"><div className="flex justify-between gap-3"><span className="text-gray-500">Prerequisites</span><strong className={track?.prerequisites_ready ? 'text-emerald-700' : 'text-amber-700'}>{track?.prerequisites_ready ? 'Complete' : 'Blocked'}</strong></div><div className="mt-1 flex justify-between gap-3"><span className="text-gray-500">Candidate head</span><code>{shortSha(manifest.candidate_revision)}</code></div></div>
        {!authorization && (
          <>
            <label className="mt-3 block text-xs font-semibold text-gray-700">Approval reference<input value={reference} onChange={(event) => setReference(event.target.value)} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm" /></label>
            <div className="mt-3 text-xs font-semibold text-gray-700">Type exactly</div><code className="mt-1.5 block overflow-x-auto rounded-xl bg-gray-950 px-3 py-2.5 text-[11px] text-gray-100">{expected}</code>
            <input value={ack} onChange={(event) => setAck(event.target.value)} className="mt-2 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-xs" placeholder="Exact authorization phrase" />
            <button type="button" disabled={authorize.isPending || !track?.prerequisites_ready || ack !== expected || !reference} onClick={() => authorize.mutate()} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-40"><Fingerprint className="h-4 w-4" /> Record owner authorization</button>
          </>
        )}
        {error && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">{error}</div>}
      </Card>

      <Card>
        <h2 className="text-sm font-bold text-gray-900">Authorization state</h2>
        {authorization ? (
          <div className="mt-3">
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800"><div className="font-bold">Authorization active</div><div className="mt-1">Reference: {authorization.approval_reference}</div><div>Approved: {formatDate(authorization.approved_at)}</div><div>Expires: {formatDate(authorization.expires_at)}</div></div>
            <div className="mt-4 border-t border-gray-100 pt-4"><div className="text-xs font-bold text-gray-700">Revoke authorization</div><code className="mt-2 block rounded-lg bg-gray-50 px-2.5 py-2 text-[11px]">{revokeExpected}</code><input value={revokeAck} onChange={(event) => setRevokeAck(event.target.value)} className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-xs" placeholder="Exact revoke phrase" /><input value={revokeReason} onChange={(event) => setRevokeReason(event.target.value)} className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-xs" placeholder="Reason" /><button type="button" disabled={revoke.isPending || revokeAck !== revokeExpected || !revokeReason} onClick={() => revoke.mutate()} className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-bold text-red-700 disabled:opacity-40">Revoke</button></div>
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-gray-300 p-8 text-center text-sm text-gray-400">No active authorization for this track.</div>
        )}
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-[11px] leading-5 text-amber-800"><strong>Separate runtime gate:</strong> even a ready and authorized track leaves real submission, autopilot, platform kill switches, and adapter maturity untouched.</div>
      </Card>
    </div>
  )
}

export default function CertificationCenter() {
  const [tab, setTab] = useState('readiness')
  const manifestQuery = useQuery({
    queryKey: ['certification-manifest'],
    queryFn: () => getCertificationManifest({ release_version: 'v2.00' }).then((response) => response.data),
  })
  const evidenceQuery = useQuery({
    queryKey: ['certification-evidence'],
    queryFn: () => getCertificationEvidence({ limit: 200 }).then((response) => response.data),
  })

  const manifest = manifestQuery.data
  const evidence = evidenceQuery.data || []
  const totalQualifying = useMemo(() => {
    if (!manifest) return 0
    const unique = new Set()
    Object.values(manifest.tracks || {}).forEach((track) => Object.entries(track.evidence || {}).forEach(([name, gate]) => { if (gate.qualifying) unique.add(name) }))
    return unique.size
  }, [manifest])

  if (manifestQuery.isLoading || evidenceQuery.isLoading) return <div className="flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading certification evidence…</div>
  if (manifestQuery.isError || evidenceQuery.isError) return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{getApiErrorMessage(manifestQuery.error || evidenceQuery.error, 'Could not load certification state')}</div>

  const runtime = manifest.runtime_controls || {}
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="section-kicker">Phase 10 · Certification & scale</p><h1 className="mt-1 text-2xl font-black tracking-tight text-gray-900">Certification Center</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-gray-500">Exact-head release evidence, full-stack shadow campaign evidence, explicit review, owner authorization, and independent runtime controls.</p></div><button type="button" onClick={() => { manifestQuery.refetch(); evidenceQuery.refetch() }} className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-700 shadow-sm"><RefreshCw className="h-3.5 w-3.5" /> Refresh</button></div>

      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4"><div className="flex items-start gap-3"><ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-700" /><div><div className="text-sm font-bold text-emerald-900">Evidence, review, authorization, and execution are separate gates.</div><p className="mt-1 text-xs leading-5 text-emerald-800">Nothing on this page silently enables real submission. Missing, stale, expired, insufficient-duration, wrong-head, hash-mismatched, or unlinked shadow evidence fails closed.</p></div></div></div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><Card><div className="flex items-center justify-between"><Gauge className="h-4 w-4 text-blue-600" /><span className="text-xl font-black text-gray-900">{totalQualifying}</span></div><div className="mt-3 text-xs font-bold text-gray-900">Qualifying evidence</div></Card><Card><div className="flex items-center justify-between"><TimerReset className="h-4 w-4 text-violet-600" /><code className="text-xs font-black text-gray-900">{shortSha(manifest.candidate_revision)}</code></div><div className="mt-3 text-xs font-bold text-gray-900">Candidate revision</div></Card><RuntimeControl label="Real submission" value={runtime.real_submission_enabled} safeWhenFalse /><RuntimeControl label="Autopilot" value={runtime.autopilot_enabled} safeWhenFalse /><RuntimeControl label="Global kill switch" value={runtime.global_kill_switch} /></div>

      <div className="flex gap-1 overflow-x-auto rounded-xl border border-gray-200 bg-white p-1 shadow-sm">{[['readiness', 'Readiness', Gauge], ['evidence', 'Evidence ledger', FileCheck2], ['authorization', 'Owner authorization', KeyRound]].map(([id, label, Icon]) => <button key={id} type="button" onClick={() => setTab(id)} className={`inline-flex flex-shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs font-bold ${tab === id ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-50'}`}><Icon className="h-3.5 w-3.5" />{label}</button>)}</div>

      {tab === 'readiness' && <div className="grid gap-4 xl:grid-cols-2"><TrackCard track={manifest.tracks.autonomous_pilot} /><TrackCard track={manifest.tracks.v2_release} /></div>}
      {tab === 'evidence' && <EvidenceLedger manifest={manifest} evidence={evidence} />}
      {tab === 'authorization' && <AuthorizationPanel manifest={manifest} />}
    </div>
  )
}
