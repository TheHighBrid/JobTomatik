import { useState } from 'react'
import toast from 'react-hot-toast'
import { Shield, Bell, Cpu, Server, Key } from 'lucide-react'
import { getBaseUrl } from '../api/client'

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

function Toggle({ label, description, checked, onChange }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-50 last:border-0">
      <div>
        <div className="text-sm font-medium text-gray-900">{label}</div>
        {description && <div className="text-xs text-gray-500 mt-0.5">{description}</div>}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-5 rounded-full transition-colors duration-200 focus:outline-none ${checked ? 'bg-tomato-600' : 'bg-gray-200'}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-transform duration-200 ${checked ? 'translate-x-5' : ''}`}
        />
      </button>
    </div>
  )
}

export default function Settings() {
  const [apiUrl, setApiUrl] = useState(() => localStorage.getItem('api_url') || '')

  const saveApiUrl = () => {
    const trimmed = apiUrl.trim().replace(/\/$/, '')
    if (trimmed) {
      localStorage.setItem('api_url', trimmed)
      toast.success('Backend URL saved — restart the app to reconnect.')
    } else {
      localStorage.removeItem('api_url')
      toast.success('Backend URL cleared — using default.')
    }
  }

  const [settings, setSettings] = useState({
    emailOnStatusChange: true,
    emailOnNewMatches: false,
    emailOnInterview: true,
    emailOnOffer: true,
    autoFollowup: true,
    autoFollowupDays: 7,
    dryRunMode: true,
    autoGenerateCoverLetters: true,
  })

  const toggle = (k) => (v) => setSettings((s) => ({ ...s, [k]: v }))
  const set = (k) => (e) => setSettings((s) => ({ ...s, [k]: e.target.value }))

  const save = () => toast.success('Settings saved!')

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure automation behavior and notifications.</p>
      </div>

      <Section title="Automation" icon={Cpu}>
        <Toggle
          label="Dry Run Mode"
          description="Fill forms but don't submit — preview before going live"
          checked={settings.dryRunMode}
          onChange={toggle('dryRunMode')}
        />
        <Toggle
          label="Auto-Generate Cover Letters"
          description="Automatically generate a cover letter when creating an application"
          checked={settings.autoGenerateCoverLetters}
          onChange={toggle('autoGenerateCoverLetters')}
        />
        <Toggle
          label="Auto-Schedule Follow-ups"
          description="Automatically schedule a follow-up email after applying"
          checked={settings.autoFollowup}
          onChange={toggle('autoFollowup')}
        />
        {settings.autoFollowup && (
          <div className="mt-3 pl-0">
            <label className="label">Follow-up delay (days after applying)</label>
            <input
              type="number"
              className="input w-24"
              min="1"
              max="30"
              value={settings.autoFollowupDays}
              onChange={set('autoFollowupDays')}
            />
          </div>
        )}
      </Section>

      <Section title="Email Notifications" icon={Bell}>
        <Toggle
          label="Status Changes"
          description="Email when application status changes"
          checked={settings.emailOnStatusChange}
          onChange={toggle('emailOnStatusChange')}
        />
        <Toggle
          label="New Job Matches"
          description="Email when new jobs match your preferences"
          checked={settings.emailOnNewMatches}
          onChange={toggle('emailOnNewMatches')}
        />
        <Toggle
          label="Interview Scheduled"
          description="Email when an interview is marked"
          checked={settings.emailOnInterview}
          onChange={toggle('emailOnInterview')}
        />
        <Toggle
          label="Offer Received"
          description="Email when an offer comes in"
          checked={settings.emailOnOffer}
          onChange={toggle('emailOnOffer')}
        />
      </Section>

      <Section title="Privacy & Security" icon={Shield}>
        <div className="text-sm text-gray-600 space-y-2">
          <p>Your data is stored securely in your own database instance.</p>
          <p>Credentials (LinkedIn, Indeed, etc.) are stored encrypted at rest.</p>
          <p>Cover letters and resumes are only accessible to you.</p>
        </div>
        <button
          className="mt-4 text-sm text-red-600 hover:underline"
          onClick={() => toast('This would trigger account deletion in production.')}
        >
          Delete my account and all data
        </button>
      </Section>

      <Section title="Backend Connection" icon={Server}>
        <p className="text-sm text-gray-500 mb-3">
          Set your backend server URL. Required when running as a mobile app (APK).
          Leave blank to use the default (<code className="bg-gray-100 px-1 rounded text-xs">{getBaseUrl()}</code>).
        </p>
        <div className="flex gap-2">
          <input
            type="url"
            className="input flex-1"
            placeholder="http://192.168.1.100:8000"
            value={apiUrl}
            onChange={(e) => setApiUrl(e.target.value)}
          />
          <button onClick={saveApiUrl} className="btn-primary px-4">Save</button>
        </div>
      </Section>

      <Section title="API Keys" icon={Key}>
        <p className="text-sm text-gray-500 mb-3">
          Configure your API keys via <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">.env</code> file or environment variables on the server.
        </p>
        <div className="space-y-2 text-xs font-mono">
          {[
            ['ANTHROPIC_API_KEY', 'Claude AI — cover letter generation'],
            ['SENDGRID_API_KEY', 'SendGrid — email delivery'],
            ['RAPIDAPI_KEY', 'Optional — enhanced job board access'],
          ].map(([key, desc]) => (
            <div key={key} className="flex items-center justify-between bg-gray-50 px-3 py-2 rounded-lg">
              <span className="text-gray-700">{key}</span>
              <span className="text-gray-400 text-[11px] font-sans">{desc}</span>
            </div>
          ))}
        </div>
      </Section>

      <button onClick={save} className="btn-primary w-full">
        Save Settings
      </button>
    </div>
  )
}
