import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { searchJobs, getTaskStatus } from '../api/client'
import {
  Search,
  MapPin,
  DollarSign,
  Loader2,
  CheckCircle2,
  Building2,
  ShieldCheck,
} from 'lucide-react'

const SOURCES = [
  { value: 'jobbank', label: 'Job Bank' },
  { value: 'indeed', label: 'Indeed' },
  { value: 'linkedin', label: 'LinkedIn' },
  { value: 'glassdoor', label: 'Glassdoor' },
  { value: 'greenhouse', label: 'Greenhouse' },
  { value: 'lever', label: 'Lever' },
  { value: 'ashby', label: 'Ashby' },
]
const ATS_SOURCES = ['greenhouse', 'lever', 'ashby']
const JOB_TYPES = [
  { value: 'full_time', label: 'Full Time' },
  { value: 'part_time', label: 'Part Time' },
  { value: 'contract', label: 'Contract' },
  { value: 'internship', label: 'Internship' },
  { value: 'remote', label: 'Remote' },
]

function parseTargets(provider, value) {
  return value
    .split(/[\n,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => {
      const [identifier, company] = entry.split('|').map((part) => part.trim())
      return {
        provider,
        identifier,
        company: company || identifier,
      }
    })
}

export default function JobSearch() {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    keywords: '',
    location: '',
    salary_min: '',
    salary_max: '',
    job_type: '',
    sources: ['jobbank', 'indeed', 'linkedin', 'glassdoor'],
    limit: 50,
  })
  const [atsInputs, setAtsInputs] = useState({
    greenhouse: '',
    lever: '',
    ashby: '',
  })
  const [taskId, setTaskId] = useState(null)
  const [taskStatus, setTaskStatus] = useState(null)

  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }))
  const setAts = (provider) => (event) =>
    setAtsInputs((current) => ({ ...current, [provider]: event.target.value }))

  const toggleSource = (source) =>
    setForm((current) => ({
      ...current,
      sources: current.sources.includes(source)
        ? current.sources.filter((item) => item !== source)
        : [...current.sources, source],
    }))

  const pollTask = async (id) => {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2000))
      try {
        const response = await getTaskStatus(id)
        const { status, result } = response.data
        setTaskStatus(status)
        if (status === 'SUCCESS') {
          const saved = result?.saved || 0
          const evaluated = result?.evaluations_created || 0
          toast.success(`Saved ${saved} jobs and created ${evaluated} evaluations.`)
          qc.invalidateQueries({ queryKey: ['jobQueue'] })
          qc.invalidateQueries({ queryKey: ['appStats'] })
          qc.invalidateQueries({ queryKey: ['intelligenceOverview'] })
          return
        }
        if (status === 'FAILURE') {
          toast.error('Search failed. Please try again.')
          return
        }
      } catch {
        // Polling retries until the bounded loop expires.
      }
    }
    toast('Search is taking longer than expected. Check your queue in a moment.')
  }

  const mutation = useMutation({
    mutationFn: () => {
      const atsTargets = ATS_SOURCES.flatMap((provider) =>
        form.sources.includes(provider) ? parseTargets(provider, atsInputs[provider]) : [],
      )
      return searchJobs({
        keywords: form.keywords,
        location: form.location || null,
        salary_min: form.salary_min ? parseInt(form.salary_min, 10) : null,
        salary_max: form.salary_max ? parseInt(form.salary_max, 10) : null,
        job_type: form.job_type || null,
        sources: form.sources,
        ats_targets: atsTargets,
        limit: parseInt(form.limit, 10),
      })
    },
    onSuccess: (response) => {
      const id = response.data.task_id
      setTaskId(id)
      setTaskStatus('PENDING')
      toast('Discovery started. Matching roles will be scored and evaluated.')
      pollTask(id)
    },
    onError: (error) => toast.error(error.response?.data?.detail || 'Search failed'),
  })

  const isRunning = mutation.isPending || (taskStatus && !['SUCCESS', 'FAILURE'].includes(taskStatus))
  const selectedAtsSources = ATS_SOURCES.filter((provider) => form.sources.includes(provider))

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Job Discovery</h1>
        <p className="text-gray-500 mt-1">
          Search broad boards and official company ATS feeds, then score every result with auditable evidence.
        </p>
      </div>

      <div className="card p-6 space-y-5">
        <div>
          <label className="label">Keywords *</label>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              className="input pl-10"
              placeholder="e.g. Fraud Investigator, AML, bilingual compliance"
              value={form.keywords}
              onChange={set('keywords')}
            />
          </div>
        </div>

        <div>
          <label className="label">Location</label>
          <div className="relative">
            <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              className="input pl-10"
              placeholder="Ottawa, Ontario or Remote"
              value={form.location}
              onChange={set('location')}
            />
          </div>
        </div>

        <div>
          <label className="label">Salary Range (CAD)</label>
          <div className="flex gap-3">
            <div className="relative flex-1">
              <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="number"
                className="input pl-9"
                placeholder="Minimum"
                value={form.salary_min}
                onChange={set('salary_min')}
              />
            </div>
            <div className="relative flex-1">
              <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="number"
                className="input pl-9"
                placeholder="Maximum"
                value={form.salary_max}
                onChange={set('salary_max')}
              />
            </div>
          </div>
        </div>

        <div>
          <label className="label">Job Type</label>
          <div className="flex flex-wrap gap-2">
            {JOB_TYPES.map(({ value, label }) => (
              <button
                type="button"
                key={value}
                onClick={() => setForm((current) => ({
                  ...current,
                  job_type: current.job_type === value ? '' : value,
                }))}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                  form.job_type === value
                    ? 'bg-tomato-600 text-white border-tomato-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-tomato-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="label">Discovery Sources</label>
          <div className="flex flex-wrap gap-2">
            {SOURCES.map(({ value, label }) => (
              <button
                type="button"
                key={value}
                onClick={() => toggleSource(value)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                  form.sources.includes(value)
                    ? 'bg-tomato-600 text-white border-tomato-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-tomato-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {selectedAtsSources.length > 0 && (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-4 space-y-4">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 rounded-xl bg-emerald-100 p-2 text-emerald-700">
                <ShieldCheck className="h-4 w-4" />
              </div>
              <div>
                <h2 className="font-semibold text-gray-900">Official company ATS boards</h2>
                <p className="text-xs text-gray-600 mt-1">
                  Enter tenant identifiers, one per line. Add an optional company label using
                  <span className="font-mono"> identifier|Company Name</span>.
                </p>
              </div>
            </div>

            {selectedAtsSources.map((provider) => (
              <div key={provider}>
                <label className="label capitalize flex items-center gap-2">
                  <Building2 className="h-4 w-4" />
                  {provider} board identifiers
                </label>
                <textarea
                  className="input min-h-20 py-2"
                  placeholder={
                    provider === 'greenhouse'
                      ? 'examplebank|Example Bank'
                      : provider === 'lever'
                        ? 'examplecompany|Example Company'
                        : 'example-org|Example Organization'
                  }
                  value={atsInputs[provider]}
                  onChange={setAts(provider)}
                />
              </div>
            ))}
          </div>
        )}

        <div>
          <label className="label">Max Results: {form.limit}</label>
          <input
            type="range"
            min="10"
            max="100"
            step="10"
            value={form.limit}
            onChange={set('limit')}
            className="w-full accent-tomato-600"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>10</span><span>50</span><span>100</span>
          </div>
        </div>

        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={!form.keywords || form.sources.length === 0 || isRunning}
          className="btn-primary w-full flex items-center justify-center gap-2"
        >
          {isRunning ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Discovering and evaluating… ({taskStatus || 'queued'})
            </>
          ) : (
            <>
              <Search className="w-4 h-4" />
              Discover Jobs
            </>
          )}
        </button>

        {taskId && taskStatus === 'SUCCESS' && (
          <div className="flex items-center gap-2 text-green-700 text-sm bg-green-50 px-4 py-3 rounded-lg">
            <CheckCircle2 className="w-4 h-4" />
            Discovery complete. Jobs, evaluations, and intelligence records are ready.
          </div>
        )}
      </div>
    </div>
  )
}
