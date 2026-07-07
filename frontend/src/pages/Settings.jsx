import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Shield, Bell, Cpu, Key, Wifi, Loader2, Bot } from 'lucide-react'
import ApiBaseUrlField from '../components/ApiBaseUrlField'
import { getSettings, updateSettings } from '../api/client'

function Section({ title, icon: Icon, children }) {
  return (
    <div className="card p-6">
      <h2 className="font-semibold text-gray-900 text-base mb-4 flex items-center gap-2">
        <Icon className="w-4 h-4 text-tomato-600" />
        {title}
      </h2>
      {children}
    </div>
  )
}

function Toggle({ label, description, checked, onChange, disabled }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-50 last:border-0">
      <div>
        <div className="text-sm font-medium text-gray-900">{label}</div>
        {description && <div className="text-xs text-gray-500 mt-0.5">{description}</div>}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-5 rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-50 ${checked ? 'bg-tomato-600' : 'bg-gray-200'}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-transform duration-200 ${checked ? 'translate-x-5' : ''}`}
        />
      </button>
    </div>
  )
}

export default function Settings() {
  const qc = useQueryClient()
  const [local, setLocal] = useState(null)

  const { data: serverSettings, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => getSettings(),
    select: (r) => r.data,
  })

  useEffect(() => {
    if (serverSettings && !local) {
      setLocal(serverSettings)
    }
  }, [serverSettings])

  const mut = useMutation({
    mutationFn: () => updateSettings(local),
    onSuccess: (res) => {
      setLocal(res.data)
      qc.invalidateQueries(['settings'])
      toast.success('Settings saved!')
    },
    onError: () => toast.error('Failed to save settings'),
  })

  const toggle = (k) => (v) => setLocal((s) => ({ ...s, [k]: v }))
  const setNum = (k) => (e) => setLocal((s) => ({ ...s, [k]: Number(e.target.value) }))

  if (isLoading || !local) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-tomato-500" />
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure automation behavior, notifications, and mobile API connection.</p>
      </div>

      <Section title="API Connection" icon={Wifi}>
        <ApiBaseUrlField />
      </Section>

      <Section title="Auto-Pilot" icon={Bot}>
        <Toggle
          label="Auto Search (every 6 hours)"
          description="Automatically search for jobs using your profile preferences"
          checked={local.auto_search_enabled}
          onChange={toggle('auto_search_enabled')}
        />
        <Toggle
          label="Auto Apply to High Matches"
          description="Automatically apply to jobs above the match threshold (requires Auto Search)"
          checked={local.auto_apply_enabled}
          onChange={toggle('auto_apply_enabled')}
        />
        {local.auto_apply_enabled && (
          <div className="mt-3 space-y-3 pl-0">
            <div>
              <label className="label">Minimum match score to auto-apply</label>
              <input
                type="range"
                min="0.4"
                max="1.0"
                step="0.05"
                className="w-full accent-tomato-600"
                value={local.auto_apply_min_score}
                onChange={setNum('auto_apply_min_score')}
              />
              <div className="text-xs text-gray-500 mt-1">{Math.round(local.auto_apply_min_score * 100)}% match required</div>
            </div>
            <div>
              <label className="label">Daily application limit</label>
              <input
                type="number"
                className="input w-20"
                min="1"
                max="50"
                value={local.auto_apply_daily_limit}
                onChange={setNum('auto_apply_daily_limit')}
              />
            </div>
          </div>
        )}
      </Section>

      <Section title="Automation" icon={Cpu}>
        <Toggle
          label="Dry Run Mode"
          description="Fill forms but don't submit — safe preview mode. Disable only when ready to go live."
          checked={local.dry_run_mode}
          onChange={toggle('dry_run_mode')}
        />
        <Toggle
          label="Auto-Generate Cover Letters"
          description="Automatically generate a cover letter when creating an application"
          checked={local.auto_generate_cover_letters}
          onChange={toggle('auto_generate_cover_letters')}
        />
        <Toggle
          label="Auto-Schedule Follow-ups"
          description="Automatically schedule a follow-up email after applying"
          checked={local.auto_followup}
          onChange={toggle('auto_followup')}
        />
        {local.auto_followup && (
          <div className="mt-3">
            <label className="label">Follow-up delay (days after applying)</label>
            <input
              type="number"
              className="input w-24"
              min="1"
              max="30"
              value={local.auto_followup_days}
              onChange={setNum('auto_followup_days')}
            />
          </div>
        )}
      </Section>

      <Section title="Email Notifications" icon={Bell}>
        <Toggle
          label="Status Changes"
          description="Email when application status changes"
          checked={local.email_on_status_change}
          onChange={toggle('email_on_status_change')}
        />
        <Toggle
          label="New Job Matches"
          description="Email when new jobs match your preferences"
          checked={local.email_on_new_matches}
          onChange={toggle('email_on_new_matches')}
        />
        <Toggle
          label="Interview Scheduled"
          description="Email when an interview is marked"
          checked={local.email_on_interview}
          onChange={toggle('email_on_interview')}
        />
        <Toggle
          label="Offer Received"
          description="Email when an offer comes in"
          checked={local.email_on_offer}
          onChange={toggle('email_on_offer')}
        />
      </Section>

      <Section title="Privacy & Security" icon={Shield}>
        <div className="text-sm text-gray-600 space-y-2">
          <p>Your data is stored locally in your own database instance.</p>
          <p>Real application submission is controlled by the <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">ALLOW_REAL_APPLICATION_SUBMIT</code> environment variable on the server. Dry Run Mode here is an additional safety layer.</p>
          <p>Cover letters and resumes are only accessible to your authenticated account.</p>
        </div>
      </Section>

      <Section title="API Keys" icon={Key}>
        <p className="text-sm text-gray-500 mb-3">
          Configure via <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">.env</code> file on the server.
        </p>
        <div className="space-y-2 text-xs font-mono">
          {[
            ['AI_PROVIDER', 'template | anthropic | gemini (template = free)'],
            ['ANTHROPIC_API_KEY', 'Claude AI cover letter generation'],
            ['GEMINI_API_KEY', 'Gemini Flash-Lite (cheap alternative)'],
            ['SENDGRID_API_KEY', 'Email delivery'],
            ['ALLOW_REAL_APPLICATION_SUBMIT', 'Set to true to enable live submit'],
          ].map(([key, desc]) => (
            <div key={key} className="flex items-center justify-between bg-gray-50 px-3 py-2 rounded-lg">
              <span className="text-gray-700">{key}</span>
              <span className="text-gray-400 text-[11px] font-sans">{desc}</span>
            </div>
          ))}
        </div>
      </Section>

      <button
        onClick={() => mut.mutate()}
        disabled={mut.isPending}
        className="btn-primary w-full flex items-center justify-center gap-2"
      >
        {mut.isPending ? <><Loader2 className="w-4 h-4 animate-spin" />Saving…</> : 'Save Settings'}
      </button>
    </div>
  )
}
