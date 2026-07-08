import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Bell, Cpu, Key, Wifi, Loader2, Rocket, Shield } from 'lucide-react'
import ApiBaseUrlField from '../components/ApiBaseUrlField'
import { getSettings, updateSettings } from '../api/client'

function Section({ title, icon: Icon, children, accent }) {
  return (
    <div className="card p-6">
      <h2 className={`font-semibold text-base mb-4 flex items-center gap-2 ${accent || 'text-gray-900'}`}>
        <Icon className="w-4 h-4" />
        {title}
      </h2>
      {children}
    </div>
  )
}

function Toggle({ label, description, checked, onChange, accent }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-50 last:border-0">
      <div className="pr-4">
        <div className="text-sm font-medium text-gray-900">{label}</div>
        {description && <div className="text-xs text-gray-500 mt-0.5">{description}</div>}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none flex-shrink-0 ${
          checked ? (accent || 'bg-tomato-600') : 'bg-gray-200'
        }`}
      >
        <span
          className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full shadow-sm transition-transform duration-200 ${checked ? 'translate-x-5' : ''}`}
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
        <p className="text-gray-500 mt-1 text-sm">Configure your autonomous job application pipeline.</p>
      </div>

      <Section title="API Connection" icon={Wifi}>
        <ApiBaseUrlField />
      </Section>

      <Section title="Auto-Pilot" icon={Rocket} accent="text-tomato-700">
        <Toggle
          label="Auto Search (every 6 hours)"
          description="Automatically search Job Bank, Indeed, LinkedIn using your profile keywords"
          checked={local.auto_search_enabled}
          onChange={toggle('auto_search_enabled')}
        />
        <Toggle
          label="Auto Apply to Matches"
          description="Automatically approve high-scoring jobs and submit applications"
          checked={local.auto_apply_enabled}
          onChange={toggle('auto_apply_enabled')}
        />
        {local.auto_apply_enabled && (
          <div className="mt-4 space-y-4 bg-gray-50 rounded-xl p-4">
            <div>
              <label className="label">Minimum match score to auto-apply</label>
              <input
                type="range"
                min="0.3"
                max="1.0"
                step="0.05"
                className="w-full accent-tomato-600 mt-1"
                value={local.auto_apply_min_score}
                onChange={setNum('auto_apply_min_score')}
              />
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>30% (aggressive)</span>
                <span className="font-semibold text-tomato-600">{Math.round(local.auto_apply_min_score * 100)}% selected</span>
                <span>100% (strict)</span>
              </div>
            </div>
            <div>
              <label className="label">Daily application limit</label>
              <input
                type="number"
                className="input w-24"
                min="1"
                max="50"
                value={local.auto_apply_daily_limit}
                onChange={setNum('auto_apply_daily_limit')}
              />
              <span className="text-xs text-gray-500 ml-2">applications/day</span>
            </div>
          </div>
        )}
      </Section>

      <Section title="Automation" icon={Cpu}>
        <Toggle
          label="Dry Run Mode"
          description="Fill forms but don't click submit. Useful for testing field detection."
          checked={local.dry_run_mode ?? false}
          onChange={toggle('dry_run_mode')}
        />
        <Toggle
          label="Auto-Generate Cover Letters"
          description="Generate a tailored cover letter before each application"
          checked={local.auto_generate_cover_letters}
          onChange={toggle('auto_generate_cover_letters')}
        />
        <Toggle
          label="Auto-Schedule Follow-ups"
          description="Send a follow-up email N days after applying"
          checked={local.auto_followup}
          onChange={toggle('auto_followup')}
        />
        {local.auto_followup && (
          <div className="mt-3 pl-1">
            <label className="label">Follow-up delay</label>
            <div className="flex items-center gap-2 mt-1">
              <input
                type="number"
                className="input w-20"
                min="1"
                max="30"
                value={local.auto_followup_days}
                onChange={setNum('auto_followup_days')}
              />
              <span className="text-sm text-gray-500">days after applying</span>
            </div>
          </div>
        )}
      </Section>

      <Section title="Email Notifications" icon={Bell}>
        <Toggle
          label="Status Changes"
          description="Email when application status updates"
          checked={local.email_on_status_change}
          onChange={toggle('email_on_status_change')}
        />
        <Toggle
          label="New Job Matches"
          description="Email when new jobs match your search"
          checked={local.email_on_new_matches}
          onChange={toggle('email_on_new_matches')}
        />
        <Toggle
          label="Interview Scheduled"
          checked={local.email_on_interview}
          onChange={toggle('email_on_interview')}
        />
        <Toggle
          label="Offer Received"
          checked={local.email_on_offer}
          onChange={toggle('email_on_offer')}
        />
      </Section>

      <Section title="AI & Integrations" icon={Key}>
        <p className="text-sm text-gray-500 mb-3">
          Configure via <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">.env</code> on the server.
          The app works 100% free without any API keys using the built-in banking/AML cover letter template.
        </p>
        <div className="space-y-2 text-xs font-mono">
          {[
            ['AI_PROVIDER', 'template (free) | anthropic | gemini'],
            ['ANTHROPIC_API_KEY', 'Optional — AI-generated cover letters'],
            ['GEMINI_API_KEY', 'Optional — cheaper AI alternative'],
            ['SENDGRID_API_KEY', 'Optional — email delivery'],
          ].map(([key, desc]) => (
            <div key={key} className="flex items-center justify-between bg-gray-50 px-3 py-2 rounded-xl">
              <span className="text-gray-700 font-medium">{key}</span>
              <span className="text-gray-400 text-[11px] font-sans ml-3 text-right">{desc}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Privacy" icon={Shield}>
        <div className="text-sm text-gray-600 space-y-2">
          <p>Your data is stored locally in your own SQLite database. Nothing is sent to any third party.</p>
          <p>Cover letters and resumes are only accessible to your authenticated account.</p>
        </div>
      </Section>

      <button
        onClick={() => mut.mutate()}
        disabled={mut.isPending}
        className="btn-primary w-full flex items-center justify-center gap-2 py-3 text-base"
      >
        {mut.isPending ? <><Loader2 className="w-4 h-4 animate-spin" />Saving…</> : 'Save Settings'}
      </button>
    </div>
  )
}
