import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, CheckCircle2, FileWarning, Loader2, RefreshCw, ShieldCheck,
} from 'lucide-react'

import { getAnswerPolicyReadiness } from '../api/client'

const COUNTRIES = [
  ['CA', 'Canada'],
  ['US', 'United States'],
  ['GB', 'United Kingdom'],
  ['GENERIC', 'Other'],
]

const PLATFORMS = [
  ['generic', 'Generic application'],
  ['greenhouse', 'Greenhouse'],
  ['lever', 'Lever'],
  ['ashby', 'Ashby'],
]

function statusTone(ready) {
  return ready
    ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
    : 'border-amber-200 bg-amber-50 text-amber-900'
}

function RequirementRow({ label, ready, detail }) {
  return (
    <div className="flex items-start gap-2 py-2 border-b border-gray-100 last:border-0">
      {ready
        ? <CheckCircle2 className="w-4 h-4 text-emerald-600 mt-0.5 flex-shrink-0" />
        : <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />}
      <div className="min-w-0">
        <p className="text-xs font-medium text-gray-900">{label}</p>
        {detail && <p className="text-[11px] text-gray-500 mt-0.5">{detail}</p>}
      </div>
    </div>
  )
}

export default function AnswerPolicyReadinessPanel() {
  const [country, setCountry] = useState('CA')
  const [platform, setPlatform] = useState('generic')

  const readiness = useQuery({
    queryKey: ['answer-policy-readiness', country, platform],
    queryFn: () => getAnswerPolicyReadiness({ country_code: country, platform }),
    select: (response) => response.data,
  })

  if (readiness.isLoading) {
    return (
      <div className="rounded-xl border border-gray-200 p-4 flex justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-tomato-500" />
      </div>
    )
  }

  if (readiness.isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4">
        <div className="flex gap-2">
          <FileWarning className="w-5 h-5 text-red-600 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-900">Readiness report unavailable</p>
            <button
              type="button"
              className="text-xs text-red-700 mt-2 inline-flex items-center gap-1"
              onClick={() => readiness.refetch()}
            >
              <RefreshCw className="w-3 h-3" /> Try again
            </button>
          </div>
        </div>
      </div>
    )
  }

  const report = readiness.data
  const ready = Boolean(report?.ready_for_unattended)
  const blockers = report?.blockers || []

  return (
    <div className="space-y-4 mb-5">
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="label">Country readiness profile</label>
          <select
            className="input w-full"
            value={country}
            onChange={(event) => setCountry(event.target.value)}
          >
            {COUNTRIES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Application platform</label>
          <select
            className="input w-full"
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
          >
            {PLATFORMS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className={`rounded-xl border p-4 ${statusTone(ready)}`}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex gap-3">
            <ShieldCheck className="w-5 h-5 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold">
                {ready ? 'Answer vault ready for unattended use' : 'Autonomy blockers detected'}
              </p>
              <p className="text-xs mt-1 opacity-80">
                {report?.summary?.profile_fields_complete}/{report?.summary?.profile_fields_required} profile fields and{' '}
                {report?.summary?.policies_ready}/{report?.summary?.policies_required} required policies are ready.
              </p>
            </div>
          </div>
          <div className="text-right flex-shrink-0">
            <p className="text-2xl font-bold">{Math.round(report?.completeness_score || 0)}%</p>
            <p className="text-[10px] uppercase tracking-wide opacity-70">complete</p>
          </div>
        </div>
      </div>

      {!ready && (
        <div className="rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-gray-900">Fix before unattended applications</h3>
            <span className="text-xs text-gray-500">{blockers.length} blocker{blockers.length === 1 ? '' : 's'}</span>
          </div>
          <div className="divide-y divide-gray-100">
            {blockers.map((blocker, index) => (
              <div key={`${blocker.code}-${blocker.field || blocker.canonical_key || index}`} className="py-2">
                <p className="text-xs font-medium text-gray-900">{blocker.message}</p>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  {blocker.field
                    ? `Profile field: ${blocker.field.replaceAll('_', ' ')}`
                    : `Policy: ${(blocker.canonical_key || blocker.code).replaceAll('_', ' ')}`}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-3">
        <div className="rounded-xl border border-gray-200 p-3">
          <p className="text-xs font-bold uppercase tracking-wide text-gray-500 mb-1">Applicant profile</p>
          {(report?.required_profile_fields || []).map((item) => (
            <RequirementRow
              key={item.key}
              label={item.label}
              ready={item.present}
              detail={item.present ? 'Available' : `Add ${item.key.replaceAll('_', ' ')}`}
            />
          ))}
        </div>
        <div className="rounded-xl border border-gray-200 p-3">
          <p className="text-xs font-bold uppercase tracking-wide text-gray-500 mb-1">Required answer policies</p>
          {(report?.required_policies || []).map((item) => (
            <RequirementRow
              key={item.canonical_key}
              label={item.label}
              ready={item.satisfied}
              detail={item.satisfied
                ? 'Confirmed, authorized, current, and conflict-free'
                : (item.blocker_codes || []).map((code) => code.replaceAll('_', ' ')).join(' · ')}
            />
          ))}
        </div>
      </div>

      {!!report?.conflicts?.length && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
          Conflicting policies are never resolved by row order. Pause or remove one overlapping policy before retrying.
        </div>
      )}
    </div>
  )
}
