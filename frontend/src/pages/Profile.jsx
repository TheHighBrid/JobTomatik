import { useState, useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useDropzone } from 'react-dropzone'
import toast from 'react-hot-toast'
import { getProfile, updateProfile, uploadResume, deleteResume } from '../api/client'
import { useAuthStore } from '../store'
import {
  User, Phone, MapPin, Link2, Globe, Upload,
  Trash2, FileText, CheckCircle2, Loader2, Building2,
} from 'lucide-react'

function Section({ title, children }) {
  return (
    <div className="card p-6">
      <h2 className="font-semibold text-gray-900 text-base mb-5">{title}</h2>
      {children}
    </div>
  )
}

function Field({ label, icon: Icon, children }) {
  return (
    <div>
      <label className="label flex items-center gap-1.5">
        {Icon && <Icon className="w-3.5 h-3.5 text-gray-400" />}
        {label}
      </label>
      {children}
    </div>
  )
}

function serializeAtsTargets(targets) {
  return (targets || [])
    .filter((target) => target?.provider && target?.identifier)
    .map((target) => {
      const company = target.company && target.company !== target.identifier
        ? `|${target.company}`
        : ''
      return `${target.provider}:${target.identifier}${company}`
    })
    .join('\n')
}

function parseAtsTargets(value) {
  const supported = new Set(['greenhouse', 'lever', 'ashby'])
  return value
    .split(/[\n,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => {
      const [providerAndIdentifier, company] = entry.split('|').map((part) => part.trim())
      const separator = providerAndIdentifier.indexOf(':')
      if (separator < 1) return null
      const provider = providerAndIdentifier.slice(0, separator).trim().toLowerCase()
      const identifier = providerAndIdentifier.slice(separator + 1).trim()
      if (!supported.has(provider) || !/^[A-Za-z0-9_-]+$/.test(identifier)) return null
      return { provider, identifier, company: company || identifier }
    })
    .filter(Boolean)
}

const DEFAULT_FORM = {
  full_name: '',
  phone: '',
  address: '',
  linkedin_url: '',
  github_url: '',
  portfolio_url: '',
  email_signature: '',
}

const DEFAULT_PREFS = {
  skills: '',
  preferred_titles: '',
  preferred_locations: '',
  min_salary: '',
  ats_targets: '',
  current_role: '',
  years_experience: '',
  key_achievements: '',
  employment_history: '',
}

export default function Profile() {
  const { updateUser } = useAuthStore()
  const qc = useQueryClient()
  const fileInputRef = useRef(null)

  const [form, setForm] = useState(DEFAULT_FORM)
  const [prefs, setPrefs] = useState(DEFAULT_PREFS)

  const { data: profile, isLoading } = useQuery({
    queryKey: ['profile'],
    queryFn: () => getProfile(),
    select: (response) => response.data,
  })

  useEffect(() => {
    if (!profile) return
    setForm({
      full_name: profile.full_name || '',
      phone: profile.phone || '',
      address: profile.address || '',
      linkedin_url: profile.linkedin_url || '',
      github_url: profile.github_url || '',
      portfolio_url: profile.portfolio_url || '',
      email_signature: profile.email_signature || '',
    })
    setPrefs({
      skills: (profile.job_preferences?.skills || []).join(', '),
      preferred_titles: (profile.job_preferences?.preferred_titles || []).join(', '),
      preferred_locations: (profile.job_preferences?.preferred_locations || []).join(', '),
      min_salary: profile.job_preferences?.min_salary || '',
      ats_targets: serializeAtsTargets(profile.job_preferences?.ats_targets),
      current_role: profile.profile_data?.current_role || '',
      years_experience: profile.profile_data?.years_experience || '',
      key_achievements: profile.profile_data?.key_achievements || '',
      employment_history: profile.profile_data?.employment_history || '',
    })
  }, [profile])

  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }))
  const setP = (key) => (event) => setPrefs((current) => ({ ...current, [key]: event.target.value }))

  const updateMut = useMutation({
    mutationFn: () => updateProfile({
      ...form,
      profile_data: {
        ...(profile?.profile_data || {}),
        current_role: prefs.current_role,
        years_experience: prefs.years_experience,
        key_achievements: prefs.key_achievements,
        employment_history: prefs.employment_history,
      },
      job_preferences: {
        ...(profile?.job_preferences || {}),
        skills: prefs.skills.split(',').map((item) => item.trim()).filter(Boolean),
        preferred_titles: prefs.preferred_titles.split(',').map((item) => item.trim()).filter(Boolean),
        preferred_locations: prefs.preferred_locations.split(',').map((item) => item.trim()).filter(Boolean),
        min_salary: prefs.min_salary ? parseInt(prefs.min_salary, 10) : null,
        ats_targets: parseAtsTargets(prefs.ats_targets),
      },
    }),
    onSuccess: (response) => {
      updateUser(response.data)
      qc.invalidateQueries({ queryKey: ['profile'] })
      toast.success('Profile saved!')
    },
    onError: () => toast.error('Failed to save profile'),
  })

  const resumeMut = useMutation({
    mutationFn: (file) => uploadResume(file),
    onSuccess: (response) => {
      updateUser(response.data)
      qc.invalidateQueries({ queryKey: ['profile'] })
      toast.success('Resume uploaded!')
    },
    onError: () => toast.error('Upload failed. Only PDF files are accepted.'),
  })

  const deleteResumeMut = useMutation({
    mutationFn: deleteResume,
    onSuccess: (response) => {
      updateUser(response.data)
      qc.invalidateQueries({ queryKey: ['profile'] })
      toast.success('Resume removed.')
    },
  })

  const handleFile = useCallback((file) => {
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toast.error('Please select a PDF file (.pdf)')
      return
    }
    resumeMut.mutate(file)
  }, [resumeMut])

  const onDrop = useCallback((accepted, rejected) => {
    const file = accepted[0] ?? rejected[0]?.file
    handleFile(file)
  }, [handleFile])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    maxFiles: 1,
    noClick: false,
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-tomato-500" />
      </div>
    )
  }

  const completionScore = [
    form.full_name, form.phone, form.address, form.linkedin_url,
    form.github_url, profile?.resume_filename,
    prefs.skills, prefs.current_role, prefs.years_experience,
  ].filter(Boolean).length

  const totalFields = 9

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in pb-24 md:pb-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Profile</h1>
          <p className="text-gray-500 mt-1">Used to auto-fill applications and generate cover letters.</p>
        </div>
        <div className="text-right">
          <div className="text-sm font-medium text-gray-700">
            {Math.round((completionScore / totalFields) * 100)}% complete
          </div>
          <div className="w-24 h-2 bg-gray-100 rounded-full mt-1 overflow-hidden">
            <div
              className="h-full bg-tomato-500 rounded-full transition-all"
              style={{ width: `${(completionScore / totalFields) * 100}%` }}
            />
          </div>
        </div>
      </div>

      <Section title="Resume (PDF)">
        {profile?.resume_filename ? (
          <div className="flex items-center gap-4 p-4 bg-green-50 border border-green-200 rounded-xl">
            <FileText className="w-8 h-8 text-green-600 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="font-medium text-green-900 truncate">{profile.resume_filename}</div>
              <div className="text-xs text-green-600 mt-0.5 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Resume on file — will be attached to applications
              </div>
            </div>
            <button
              type="button"
              onClick={() => deleteResumeMut.mutate()}
              disabled={deleteResumeMut.isPending}
              className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <div
              {...getRootProps()}
              className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
                isDragActive
                  ? 'border-tomato-400 bg-tomato-50'
                  : 'border-gray-200 hover:border-tomato-300 hover:bg-gray-50'
              }`}
            >
              <input {...getInputProps()} />
              {resumeMut.isPending ? (
                <Loader2 className="w-8 h-8 animate-spin text-tomato-500 mx-auto mb-2" />
              ) : (
                <Upload className="w-7 h-7 text-gray-400 mx-auto mb-2" />
              )}
              <p className="text-sm text-gray-600 font-medium">
                {isDragActive ? 'Drop your PDF here' : 'Drag & drop your resume PDF'}
              </p>
              <p className="text-xs text-gray-400 mt-1">or use the button below</p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              className="hidden"
              disabled={resumeMut.isPending}
              onChange={(event) => handleFile(event.target.files?.[0])}
            />
            <button
              type="button"
              disabled={resumeMut.isPending}
              onClick={() => fileInputRef.current?.click()}
              className="btn-secondary w-full flex items-center justify-center gap-2 text-sm"
            >
              {resumeMut.isPending
                ? <><Loader2 className="w-4 h-4 animate-spin" />Uploading…</>
                : <><Upload className="w-4 h-4" />Browse & Upload PDF</>
              }
            </button>
          </div>
        )}
      </Section>

      <Section title="Personal Information">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Full Name" icon={User}>
            <input type="text" className="input" value={form.full_name} onChange={set('full_name')} />
          </Field>
          <Field label="Phone" icon={Phone}>
            <input type="tel" className="input" placeholder="+1 (555) 000-0000" value={form.phone} onChange={set('phone')} />
          </Field>
          <div className="md:col-span-2">
            <Field label="Address / City" icon={MapPin}>
              <input type="text" className="input" placeholder="Ottawa, ON" value={form.address} onChange={set('address')} />
            </Field>
          </div>
          <Field label="LinkedIn URL" icon={Link2}>
            <input type="url" className="input" placeholder="https://linkedin.com/in/..." value={form.linkedin_url} onChange={set('linkedin_url')} />
          </Field>
          <Field label="GitHub URL" icon={Link2}>
            <input type="url" className="input" placeholder="https://github.com/..." value={form.github_url} onChange={set('github_url')} />
          </Field>
          <div className="md:col-span-2">
            <Field label="Portfolio / Website" icon={Globe}>
              <input type="url" className="input" placeholder="https://yoursite.com" value={form.portfolio_url} onChange={set('portfolio_url')} />
            </Field>
          </div>
        </div>
      </Section>

      <Section title="Career Profile">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Current / Most Recent Role">
              <input type="text" className="input" placeholder="Fraud Investigator" value={prefs.current_role} onChange={setP('current_role')} />
            </Field>
            <Field label="Years of Experience">
              <input type="text" className="input" placeholder="5" value={prefs.years_experience} onChange={setP('years_experience')} />
            </Field>
          </div>
          <Field label="Key Achievements (used in cover letters)">
            <textarea
              className="input min-h-[80px] resize-none"
              placeholder="Resolved complex investigations and maintained audit-ready case notes…"
              value={prefs.key_achievements}
              onChange={setP('key_achievements')}
            />
          </Field>
          <Field label="Employment History (used in cover letters)">
            <textarea
              className="input min-h-[110px] resize-y"
              placeholder={"TD Bank | Role | Relevant experience\nRBC | Role | Relevant experience\nBMO | Loan Officer | Lending and client assessment\nScotiabank | Role | Relevant experience\nTangerine | Role | Relevant experience"}
              value={prefs.employment_history}
              onChange={setP('employment_history')}
            />
            <p className="text-xs text-gray-400 mt-1">
              Use one employer per line. Cover letters will name where each experience was gained and will not invent missing details.
            </p>
          </Field>
        </div>
      </Section>

      <Section title="Job Preferences">
        <div className="space-y-4">
          <Field label="Skills (comma-separated)">
            <input type="text" className="input" placeholder="Fraud, AML, KYC, bilingual" value={prefs.skills} onChange={setP('skills')} />
          </Field>
          <Field label="Target Job Titles (comma-separated)">
            <input type="text" className="input" placeholder="Fraud Investigator, AML Analyst" value={prefs.preferred_titles} onChange={setP('preferred_titles')} />
          </Field>
          <Field label="Preferred Locations (comma-separated)">
            <input type="text" className="input" placeholder="Ottawa, Gatineau, Remote" value={prefs.preferred_locations} onChange={setP('preferred_locations')} />
          </Field>
          <Field label="Minimum Salary (CAD / year)">
            <input type="number" className="input" placeholder="65000" value={prefs.min_salary} onChange={setP('min_salary')} />
          </Field>
          <Field label="Official ATS Boards" icon={Building2}>
            <textarea
              className="input min-h-[110px] resize-y font-mono text-xs"
              placeholder={"greenhouse:example-bank|Example Bank\nlever:example-fintech|Example Fintech\nashby:example-org|Example Organization"}
              value={prefs.ats_targets}
              onChange={setP('ats_targets')}
            />
            <p className="text-xs text-gray-400 mt-1">
              One board per line using provider:identifier|Company. These targets power scheduled official-API discovery.
            </p>
          </Field>
        </div>
      </Section>

      <Section title="Email Signature">
        <textarea
          className="input min-h-[80px] resize-none font-mono text-xs"
          placeholder="Jane Smith | jane@example.com | (555) 000-0000 | github.com/jane"
          value={form.email_signature}
          onChange={set('email_signature')}
        />
        <p className="text-xs text-gray-400 mt-1">Appended to follow-up emails.</p>
      </Section>

      <button
        type="button"
        onClick={() => updateMut.mutate()}
        disabled={updateMut.isPending}
        className="btn-primary w-full py-3 text-base"
      >
        {updateMut.isPending ? (
          <span className="flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />Saving…</span>
        ) : 'Save Profile'}
      </button>
    </div>
  )
}
