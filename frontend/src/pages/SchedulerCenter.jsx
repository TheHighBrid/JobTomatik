import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlarmClock,
  Ban,
  CalendarClock,
  CheckCircle2,
  CircleGauge,
  Filter,
  Loader2,
  Play,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { getApiErrorMessage, getSettings, updateSettings } from '../api/client'
import { getSchedulerPreview, runSchedulerCycle } from '../api/scheduler'

const PLATFORM_OPTIONS = ['greenhouse', 'lever', 'ashby', 'smartrecruiters', 'workday']
const SOURCE_OPTIONS = ['jobbank', 'linkedin', 'indeed', 'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'workday']

function Toggle({ label, description, checked, onChange }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-gray-100 last:border-0">
      <div>
        <p className="text-sm font-semibold text-gray-900">{label}</p>
        {description && <p className="mt-0.5 text-xs text-gray-500">{description}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 flex-shrink-0 rounded-full transition ${checked ? 'bg-tomato-600' : 'bg-gray-200'}`}
      >
        <span className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
      </button>
    </div>
  )
}

function CsvField({ label, description, value, onChange, placeholder }) {
  const text = Array.isArray(value) ? value.join(', ') : ''
  return (
    <label className="block">
      <span className="text-xs font-semibold text-gray-700">{label}</span>
      {description && <span className="block text-[11px] text-gray-500 mt-0.5">{description}</span>}
      <input
        className="input mt-1 w-full"
        value={text}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value.split(',').map((item) => item.trim()).filter(Boolean))}
      />
    </label>
  )
}

function Pill({ children, tone = 'neutral' }) {
  const tones = {
    neutral: 'bg-gray-100 text-gray-700 border-gray-200',
    good: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    warn: 'bg-amber-50 text-amber-700 border-amber-200',
    bad: 'bg-red-50 text-red-700 border-red-200',
    info: 'bg-blue-50 text-blue-700 border-blue-200',
  }
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${tones[tone]}`}>{children}</span>
}

function Card({ title, icon: Icon, children, aside }) {
  return (
    <section className="card p-5 md:p-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-center gap-2.5">
          <span className="brand-icon-well h-9 w-9"><Icon className="h-4 w-4" /></span>
          <h2 className="text-base font-bold text-gray-900">{title}</h2>
        </div>
        {aside}
      </div>
      {children}
    </section>
  )
}

function DecisionBadge({ decision }) {
  if (decision?.allowed) return <Pill tone="good">Allowed by policy</Pill>
  return <Pill tone="bad">{decision?.code || 'Blocked'}</Pill>
}

export default function SchedulerCenter() {
  const queryClient = useQueryClient()
  const [local, setLocal] = useState(null)

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    select: (response) => response.data,
  })
  const previewQuery = useQuery({
    queryKey: ['scheduler-preview'],
    queryFn: () => getSchedulerPreview({ candidate_limit: 30 }),
    select: (response) => response.data,
    refetchInterval: 30_000,
  })

  useEffect(() => {
    if (settingsQuery.data && local === null) setLocal(settingsQuery.data)
  }, [settingsQuery.data, local])

  const saveMutation = useMutation({
    mutationFn: () => updateSettings(local),
    onSuccess: (response) => {
      setLocal(response.data)
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['scheduler-preview'] })
      toast.success('Scheduler policy saved')
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not save scheduler policy')),
  })

  const runMutation = useMutation({
    mutationFn: runSchedulerCycle,
    onSuccess: (response) => {
      toast.success(`Scheduler cycle queued${response.data?.celery_task_id ? ` · ${response.data.celery_task_id}` : ''}`)
      queryClient.invalidateQueries({ queryKey: ['scheduler-preview'] })
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Scheduler cycle was blocked')),
  })

  const preview = previewQuery.data
  const platforms = preview?.platform_maturities || {}
  const candidateSummary = preview?.summary || {}
  const selectedPlatforms = useMemo(() => new Set(local?.autopilot_enabled_platforms || []), [local?.autopilot_enabled_platforms])

  const setValue = (key, value) => setLocal((current) => ({ ...current, [key]: value }))
  const setNumber = (key, value) => {
    const parsed = Number(value)
    setValue(key, Number.isFinite(parsed) ? parsed : 0)
  }

  const toggleChoice = (key, value) => {
    const current = new Set(local?.[key] || [])
    if (current.has(value)) current.delete(value)
    else current.add(value)
    setValue(key, [...current])
  }

  if (settingsQuery.isLoading || !local) {
    return <div className="flex justify-center py-24"><Loader2 className="h-8 w-8 animate-spin text-tomato-500" /></div>
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="section-kicker">Phase 8 · bounded autonomy</p>
          <h1 className="mt-1 text-2xl md:text-3xl font-extrabold tracking-tight text-gray-900">Scheduler Center</h1>
          <p className="mt-2 max-w-3xl text-sm text-gray-500">
            Define exactly what JobTomatik may discover and consider unattended. Every application candidate still requires a live <code>certified_autonomous</code> adapter and is re-checked by the worker before browser execution.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary flex items-center gap-2"
            onClick={() => previewQuery.refetch()}
            disabled={previewQuery.isFetching}
          >
            <RefreshCw className={`h-4 w-4 ${previewQuery.isFetching ? 'animate-spin' : ''}`} /> Refresh preview
          </button>
          <button
            type="button"
            className="btn-primary flex items-center gap-2"
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
          >
            {runMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Run bounded cycle
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 flex gap-3">
        <ShieldCheck className="h-5 w-5 flex-shrink-0 text-amber-700 mt-0.5" />
        <div className="text-sm text-amber-900">
          <p className="font-bold">Scheduler policy is not submission permission.</p>
          <p className="mt-1 text-amber-800">Global autopilot, real-submit configuration, per-platform opt-in, adapter maturity, answer policies, idempotency, circuit breakers, and confirmation-evidence gates remain authoritative. CAPTCHA, MFA, identity checks, assessments, and ambiguous required answers still stop for review.</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Scheduler state</p>
          <p className="mt-2 text-lg font-bold text-gray-900">{preview?.scheduler_state?.replaceAll('_', ' ') || 'Loading'}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Global autopilot</p>
          <p className="mt-2 text-lg font-bold text-gray-900">{preview?.global_autopilot_enabled ? 'Enabled' : 'Disabled'}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Policy-allowed candidates</p>
          <p className="mt-2 text-lg font-bold text-gray-900">{candidateSummary.allowed_candidate_count ?? 0}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Real submit environment</p>
          <p className="mt-2 text-lg font-bold text-gray-900">{preview?.real_submission_enabled ? 'Enabled' : 'Off'}</p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.05fr_.95fr]">
        <div className="space-y-6">
          <Card title="Scheduler switches" icon={CircleGauge}>
            <Toggle
              label="Scheduled discovery"
              description="Run saved discovery every scheduler interval when the global operations profile allows it."
              checked={Boolean(local.auto_search_enabled)}
              onChange={(value) => setValue('auto_search_enabled', value)}
            />
            <Toggle
              label="Autonomous candidate processing"
              description="Consider policy-matching queued jobs. Non-certified adapters remain blocked."
              checked={Boolean(local.auto_apply_enabled)}
              onChange={(value) => setValue('auto_apply_enabled', value)}
            />
            <Toggle
              label="Dry-run mode"
              description="Force every scheduled application attempt to remain a preview even if the server's real-submit gate is enabled."
              checked={local.dry_run_mode !== false}
              onChange={(value) => setValue('dry_run_mode', value)}
            />
          </Card>

          <Card title="Saved discovery policy" icon={Search}>
            <div className="grid gap-4 md:grid-cols-2">
              <CsvField
                label="Keywords"
                description="Leave blank to use preferred titles or skills from Profile. No generic fallback is invented."
                value={local.scheduler_search_keywords}
                onChange={(value) => setValue('scheduler_search_keywords', value)}
                placeholder="AML analyst, fraud analyst"
              />
              <label className="block">
                <span className="text-xs font-semibold text-gray-700">Search location</span>
                <span className="block text-[11px] text-gray-500 mt-0.5">Leave blank to use the first preferred location from Profile.</span>
                <input className="input mt-1 w-full" value={local.scheduler_search_location || ''} onChange={(event) => setValue('scheduler_search_location', event.target.value)} placeholder="Ottawa, Ontario" />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-gray-700">Results per search</span>
                <input type="number" min="1" max="100" className="input mt-1 w-full" value={local.scheduler_search_limit} onChange={(event) => setNumber('scheduler_search_limit', event.target.value)} />
              </label>
              <div>
                <span className="text-xs font-semibold text-gray-700">Sources</span>
                <div className="mt-2 flex flex-wrap gap-2">
                  {SOURCE_OPTIONS.map((source) => {
                    const checked = (local.scheduler_search_sources || []).includes(source)
                    return (
                      <button key={source} type="button" onClick={() => toggleChoice('scheduler_search_sources', source)} className={`rounded-xl border px-3 py-2 text-xs font-semibold ${checked ? 'border-tomato-300 bg-tomato-50 text-tomato-700' : 'border-gray-200 bg-white text-gray-600'}`}>
                        {checked ? '✓ ' : ''}{source}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
            <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
              <span className="font-semibold text-gray-900">Preview: </span>
              {preview?.search_plan?.ready ? `${preview.search_plan.search_params?.keywords} · ${preview.search_plan.search_params?.location}` : preview?.search_plan?.reason || 'Loading search plan…'}
            </div>
          </Card>

          <Card title="Caps and quiet hours" icon={CalendarClock}>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <label><span className="label">Daily cap</span><input type="number" min="1" max="50" className="input w-full" value={local.auto_apply_daily_limit} onChange={(event) => setNumber('auto_apply_daily_limit', event.target.value)} /></label>
              <label><span className="label">Weekly cap</span><input type="number" min="1" max="200" className="input w-full" value={local.auto_apply_weekly_limit} onChange={(event) => setNumber('auto_apply_weekly_limit', event.target.value)} /></label>
              <label><span className="label">Per-employer daily cap</span><input type="number" min="1" max="10" className="input w-full" value={local.auto_apply_daily_per_employer_limit} onChange={(event) => setNumber('auto_apply_daily_per_employer_limit', event.target.value)} /></label>
              <label><span className="label">Quiet hours start UTC</span><input type="number" min="0" max="23" className="input w-full" value={local.quiet_hours_start_utc} onChange={(event) => setNumber('quiet_hours_start_utc', event.target.value)} /></label>
              <label><span className="label">Quiet hours end UTC</span><input type="number" min="0" max="23" className="input w-full" value={local.quiet_hours_end_utc} onChange={(event) => setNumber('quiet_hours_end_utc', event.target.value)} /></label>
              <label><span className="label">Minimum match</span><input type="number" min="0.3" max="1" step="0.05" className="input w-full" value={local.auto_apply_min_score} onChange={(event) => setNumber('auto_apply_min_score', event.target.value)} /></label>
            </div>
          </Card>

          <Card title="Job and employer constraints" icon={Filter}>
            <div className="grid gap-4 md:grid-cols-2">
              <CsvField label="Employer allow list" description="Optional. If populated, only these employers may pass unattended policy." value={local.autopilot_employer_allow_list} onChange={(value) => setValue('autopilot_employer_allow_list', value)} placeholder="Company A, Company B" />
              <CsvField label="Employer exclude list" value={local.autopilot_employer_exclude_list} onChange={(value) => setValue('autopilot_employer_exclude_list', value)} placeholder="Excluded employer" />
              <CsvField label="Allowed locations" value={local.autopilot_allowed_locations} onChange={(value) => setValue('autopilot_allowed_locations', value.map((item) => item.toLowerCase()))} placeholder="ottawa, ontario, remote" />
              <CsvField label="Allowed seniority" value={local.autopilot_allowed_seniority} onChange={(value) => setValue('autopilot_allowed_seniority', value.map((item) => item.toLowerCase()))} placeholder="entry, mid, senior" />
              <CsvField label="Allowed languages" value={local.autopilot_allowed_languages} onChange={(value) => setValue('autopilot_allowed_languages', value.map((item) => item.toLowerCase()))} placeholder="english, french" />
              <label><span className="label">Minimum salary</span><input type="number" min="0" className="input w-full" value={local.autopilot_min_salary} onChange={(event) => setNumber('autopilot_min_salary', event.target.value)} /></label>
            </div>
          </Card>

          <Card title="Autonomous platform opt-in" icon={ShieldCheck}>
            <p className="text-xs text-gray-500 mb-3">Opt-in alone does not authorize a platform. Runtime maturity must independently equal <code>certified_autonomous</code>.</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {PLATFORM_OPTIONS.map((platform) => {
                const selected = selectedPlatforms.has(platform)
                const maturity = platforms[platform]
                return (
                  <button key={platform} type="button" onClick={() => toggleChoice('autopilot_enabled_platforms', platform)} className={`flex items-center justify-between rounded-xl border px-3 py-3 text-left ${selected ? 'border-tomato-300 bg-tomato-50' : 'border-gray-200 bg-white'}`}>
                    <span><span className="block text-sm font-semibold text-gray-900">{platform}</span><span className="block text-[11px] text-gray-500">{maturity || 'unknown maturity'}</span></span>
                    {selected ? <CheckCircle2 className="h-5 w-5 text-tomato-600" /> : <Ban className="h-5 w-5 text-gray-300" />}
                  </button>
                )
              })}
            </div>
          </Card>

          <button type="button" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="btn-primary w-full flex items-center justify-center gap-2 py-3">
            {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save scheduler policy
          </button>
        </div>

        <div className="space-y-6">
          <Card title="Current policy verdict" icon={AlarmClock} aside={preview?.user_policy?.allowed ? <Pill tone="good">Allowed</Pill> : <Pill tone="bad">Blocked</Pill>}>
            <p className="text-sm font-semibold text-gray-900">{preview?.user_policy?.code?.replaceAll('_', ' ') || 'Loading'}</p>
            <p className="mt-1 text-sm text-gray-500">{preview?.user_policy?.reason}</p>
            <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl bg-gray-50 p-3"><span className="block text-gray-500">Daily remaining</span><span className="font-bold text-gray-900">{preview?.user_policy?.metadata?.remaining_daily ?? '—'}</span></div>
              <div className="rounded-xl bg-gray-50 p-3"><span className="block text-gray-500">Weekly remaining</span><span className="font-bold text-gray-900">{preview?.user_policy?.metadata?.remaining_weekly ?? '—'}</span></div>
            </div>
          </Card>

          <Card title="Candidate queue preview" icon={TriangleAlert} aside={<Pill tone="info">{candidateSummary.candidate_count ?? 0} inspected</Pill>}>
            <div className="space-y-3 max-h-[920px] overflow-y-auto pr-1">
              {(preview?.candidates || []).length === 0 && <p className="text-sm text-gray-500">No queued jobs meet the minimum match threshold.</p>}
              {(preview?.candidates || []).map((candidate) => (
                <article key={candidate.job_id} className="rounded-2xl border border-gray-200 p-4 bg-white">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-bold text-gray-900 truncate">{candidate.title}</p>
                      <p className="text-xs text-gray-500 truncate">{candidate.company} · {candidate.location || 'Location unknown'}</p>
                    </div>
                    <DecisionBadge decision={candidate.policy_decision} />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Pill>{Math.round((candidate.relevance_score || 0) * 100)}% match</Pill>
                    <Pill tone="info">Priority {candidate.priority_score}</Pill>
                    {candidate.priority_evidence?.days_remaining != null && <Pill tone={candidate.priority_evidence.days_remaining <= 3 ? 'warn' : 'neutral'}>{candidate.priority_evidence.days_remaining}d remaining</Pill>}
                  </div>
                  {!candidate.policy_decision?.allowed && (
                    <p className="mt-3 text-xs text-red-600">{candidate.policy_decision?.reason}</p>
                  )}
                </article>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
