import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Bell, Cpu, Key, Wifi, Loader2, Rocket, Shield, ArrowRight } from 'lucide-react'
import ApiBaseUrlField from '../components/ApiBaseUrlField'
import AnswerPolicyReadinessPanel from '../components/AnswerPolicyReadinessPanel'
import AnswerPolicyVault from '../components/AnswerPolicyVault'
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
        <p className="text-gray-500 mt-1 text-sm">Configure account, automation, answer-policy, and integration preferences.</p>
      </div>

      <Section title="API Connection" icon={Wifi}>
        <ApiBaseUrlField />
      </Section>

      <Section title="Bounded Scheduler" icon={Rocket} accent="text-tomato-700">
        <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
          <p className="text-sm font-semibold text-gray-900">Scheduler Center is the authoritative policy surface.</p>
          <p className="mt-1 text-xs leading-5 text-gray-500">
            Configure saved discovery, minimum match, daily and weekly caps, quiet hours, employer rules, platform opt-in, and the live policy preview in one place. Scheduler policy never replaces adapter maturity or submission safety gates.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-600">
            <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1">Discovery: {local.auto_search_enabled ? 'on' : 'off'}</span>
            <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1">Candidate processing: {local.auto_apply_enabled ? 'on' : 'off'}</span>
            <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1">Dry run: {local.dry_run_mode !== false ? 'on' : 'off'}</span>
          </div>
          <Link to="/scheduler" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-tomato-700 hover:text-tomato-800">
            Open Scheduler Center <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </Section>

      <Section title="Automation" icon={Cpu}>
        <Toggle
          label="Dry Run Mode"
          description="Fill forms but do not click submit. This remains the safe default and is also visible in Scheduler Center."
          checked={local.dry_run_mode ?? true}
          onChange={toggle('dry_run_mode')}
        />
        <Toggle
          label="Auto-Generate Cover Letters"
          description="Generate a tailored cover letter before each application"
          checked={local.auto_generate_cover_letters}
          onChange={toggle('auto_generate_cover_letters')}
        />
        <Toggle
          label="Auto-Prepare Follow-up Drafts"
          description="Prepare an unapproved draft N days after a confirmed application. No recipient is selected and nothing is sent automatically."
          checked={local.auto_followup}
          onChange={toggle('auto_followup')}
        />
        {local.auto_followup && (
          <div className="mt-3 pl-1">
            <label className="label">Draft target date</label>
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

      <Section title="Answer Policy Vault" icon={Shield}>
        <AnswerPolicyReadinessPanel />
        <AnswerPolicyVault />
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
          The app works without paid AI using the built-in cover-letter templates.
        </p>
        <div className="space-y-2 text-xs font-mono">
          {[
            ['AI_PROVIDER', 'template (free) | anthropic | gemini'],
            ['ANTHROPIC_API_KEY', 'Optional · AI-generated cover letters'],
            ['GEMINI_API_KEY', 'Optional · alternative AI provider'],
            ['SENDGRID_API_KEY', 'Required for approved recruiter follow-up delivery'],
            ['ALLOW_REAL_FOLLOWUP_SEND', 'Independent outbound recruiter-email kill switch'],
            ['ANSWER_VAULT_KEY', 'Optional · dedicated answer encryption key'],
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
          <p>Profile data and encrypted answer policies are stored in your configured JobTomatik database.</p>
          <p>External AI or email providers receive data only when you configure and use those integrations.</p>
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
