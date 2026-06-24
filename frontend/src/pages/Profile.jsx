import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useDropzone } from 'react-dropzone'
import toast from 'react-hot-toast'
import { getProfile, updateProfile, uploadResume, deleteResume } from '../api/client'
import { useAuthStore } from '../store'
import {
  User, Phone, MapPin, Linkedin, Github, Globe, Upload,
  Trash2, FileText, CheckCircle2, Loader2
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

export default function Profile() {
  const { updateUser } = useAuthStore()
  const qc = useQueryClient()

  const { data: profile, isLoading } = useQuery({
    queryKey: ['profile'],
    queryFn: () => getProfile(),
    select: (r) => r.data,
  })

  const [form, setForm] = useState(null)
  const [prefs, setPrefs] = useState(null)

  if (profile && !form) {
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
      current_role: profile.profile_data?.current_role || '',
      years_experience: profile.profile_data?.years_experience || '',
      key_achievements: profile.profile_data?.key_achievements || '',
    })
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const setP = (k) => (e) => setPrefs((p) => ({ ...p, [k]: e.target.value }))

  const updateMut = useMutation({
    mutationFn: () => updateProfile({
      ...form,
      profile_data: {
        current_role: prefs.current_role,
        years_experience: prefs.years_experience,
        key_achievements: prefs.key_achievements,
      },
      job_preferences: {
        skills: prefs.skills.split(',').map((s) => s.trim()).filter(Boolean),
        preferred_titles: prefs.preferred_titles.split(',').map((s) => s.trim()).filter(Boolean),
        preferred_locations: prefs.preferred_locations.split(',').map((s) => s.trim()).filter(Boolean),
        min_salary: prefs.min_salary ? parseInt(prefs.min_salary) : null,
      },
    }),
    onSuccess: (res) => {
      updateUser(res.data)
      qc.invalidateQueries(['profile'])
      toast.success('Profile saved!')
    },
    onError: () => toast.error('Failed to save profile'),
  })

  const resumeMut = useMutation({
    mutationFn: (file) => uploadResume(file),
    onSuccess: (res) => {
      updateUser(res.data)
      qc.invalidateQueries(['profile'])
      toast.success('Resume uploaded!')
    },
    onError: () => toast.error('Upload failed. Only PDF files are accepted.'),
  })

  const deleteResumeMut = useMutation({
    mutationFn: deleteResume,
    onSuccess: (res) => {
      updateUser(res.data)
      qc.invalidateQueries(['profile'])
      toast.success('Resume removed.')
    },
  })

  const onDrop = useCallback((acceptedFiles) => {
    const file = acceptedFiles[0]
    if (file) resumeMut.mutate(file)
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    maxFiles: 1,
  })

  if (isLoading || !form) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-tomato-500" />
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Profile</h1>
        <p className="text-gray-500 mt-1">This information is used to auto-fill applications.</p>
      </div>

      {/* Resume */}
      <Section title="Resume">
        {profile?.resume_filename ? (
          <div className="flex items-center gap-4 p-4 bg-green-50 border border-green-200 rounded-xl">
            <FileText className="w-8 h-8 text-green-600 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="font-medium text-green-900 truncate">{profile.resume_filename}</div>
              <div className="text-xs text-green-600 mt-0.5 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Resume on file
              </div>
            </div>
            <button
              onClick={() => deleteResumeMut.mutate()}
              disabled={deleteResumeMut.isPending}
              className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
              isDragActive
                ? 'border-tomato-400 bg-tomato-50'
                : 'border-gray-200 hover:border-tomato-300 hover:bg-gray-50'
            }`}
          >
            <input {...getInputProps()} />
            {resumeMut.isPending ? (
              <Loader2 className="w-8 h-8 animate-spin text-tomato-500 mx-auto mb-2" />
            ) : (
              <Upload className="w-8 h-8 text-gray-400 mx-auto mb-2" />
            )}
            <p className="text-sm text-gray-600 font-medium">
              {isDragActive ? 'Drop your resume here' : 'Drag & drop your resume (PDF)'}
            </p>
            <p className="text-xs text-gray-400 mt-1">or click to browse</p>
          </div>
        )}
      </Section>

      {/* Personal info */}
      <Section title="Personal Information">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Full Name" icon={User}>
            <input type="text" className="input" value={form.full_name} onChange={set('full_name')} />
          </Field>
          <Field label="Phone" icon={Phone}>
            <input type="tel" className="input" placeholder="+1 (555) 000-0000" value={form.phone} onChange={set('phone')} />
          </Field>
          <div className="md:col-span-2">
            <Field label="Address" icon={MapPin}>
              <input type="text" className="input" placeholder="San Francisco, CA 94105" value={form.address} onChange={set('address')} />
            </Field>
          </div>
          <Field label="LinkedIn URL" icon={Linkedin}>
            <input type="url" className="input" placeholder="https://linkedin.com/in/..." value={form.linkedin_url} onChange={set('linkedin_url')} />
          </Field>
          <Field label="GitHub URL" icon={Github}>
            <input type="url" className="input" placeholder="https://github.com/..." value={form.github_url} onChange={set('github_url')} />
          </Field>
          <div className="md:col-span-2">
            <Field label="Portfolio / Website" icon={Globe}>
              <input type="url" className="input" placeholder="https://yoursite.com" value={form.portfolio_url} onChange={set('portfolio_url')} />
            </Field>
          </div>
        </div>
      </Section>

      {/* Career profile */}
      <Section title="Career Profile">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Current / Most Recent Role">
              <input type="text" className="input" placeholder="Senior Software Engineer" value={prefs.current_role} onChange={setP('current_role')} />
            </Field>
            <Field label="Years of Experience">
              <input type="text" className="input" placeholder="5" value={prefs.years_experience} onChange={setP('years_experience')} />
            </Field>
          </div>
          <Field label="Key Achievements (used in cover letters)">
            <textarea
              className="input min-h-[80px] resize-none"
              placeholder="Led migration from monolith to microservices, reducing latency by 40%…"
              value={prefs.key_achievements}
              onChange={setP('key_achievements')}
            />
          </Field>
        </div>
      </Section>

      {/* Job preferences */}
      <Section title="Job Preferences">
        <div className="space-y-4">
          <Field label="Skills (comma-separated)">
            <input type="text" className="input" placeholder="Python, React, PostgreSQL, AWS" value={prefs.skills} onChange={setP('skills')} />
          </Field>
          <Field label="Preferred Job Titles (comma-separated)">
            <input type="text" className="input" placeholder="Senior Engineer, Staff Engineer, Tech Lead" value={prefs.preferred_titles} onChange={setP('preferred_titles')} />
          </Field>
          <Field label="Preferred Locations (comma-separated)">
            <input type="text" className="input" placeholder="San Francisco, Remote, New York" value={prefs.preferred_locations} onChange={setP('preferred_locations')} />
          </Field>
          <Field label="Minimum Salary (USD)">
            <input type="number" className="input" placeholder="150000" value={prefs.min_salary} onChange={setP('min_salary')} />
          </Field>
        </div>
      </Section>

      {/* Email signature */}
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
        onClick={() => updateMut.mutate()}
        disabled={updateMut.isPending}
        className="btn-primary w-full"
      >
        {updateMut.isPending ? 'Saving…' : 'Save Profile'}
      </button>
    </div>
  )
}
