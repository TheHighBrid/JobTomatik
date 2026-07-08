import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { searchJobs, getTaskStatus } from '../api/client'
import { Search, MapPin, DollarSign, Briefcase, Loader2, CheckCircle2 } from 'lucide-react'

const SOURCES = ['jobbank', 'indeed', 'linkedin', 'glassdoor']
const JOB_TYPES = [
  { value: 'full_time', label: 'Full Time' },
  { value: 'part_time', label: 'Part Time' },
  { value: 'contract', label: 'Contract' },
  { value: 'internship', label: 'Internship' },
  { value: 'remote', label: 'Remote' },
]

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
  const [taskId, setTaskId] = useState(null)
  const [taskStatus, setTaskStatus] = useState(null)

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const toggleSource = (s) =>
    setForm((f) => ({
      ...f,
      sources: f.sources.includes(s) ? f.sources.filter((x) => x !== s) : [...f.sources, s],
    }))

  const pollTask = async (id) => {
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const res = await getTaskStatus(id)
        const { status, result } = res.data
        setTaskStatus(status)
        if (status === 'SUCCESS') {
          toast.success(`Found ${result?.saved || 0} new jobs! Check your queue.`)
          qc.invalidateQueries(['jobQueue'])
          qc.invalidateQueries(['appStats'])
          return
        }
        if (status === 'FAILURE') {
          toast.error('Search failed. Please try again.')
          return
        }
      } catch {}
    }
    toast('Search is taking longer than expected. Check your queue in a moment.')
  }

  const mut = useMutation({
    mutationFn: () =>
      searchJobs({
        keywords: form.keywords,
        location: form.location || null,
        salary_min: form.salary_min ? parseInt(form.salary_min) : null,
        salary_max: form.salary_max ? parseInt(form.salary_max) : null,
        job_type: form.job_type || null,
        sources: form.sources,
        limit: parseInt(form.limit),
      }),
    onSuccess: (res) => {
      const id = res.data.task_id
      setTaskId(id)
      setTaskStatus('PENDING')
      toast('Search started! Results will appear in your queue.')
      pollTask(id)
    },
    onError: (err) => toast.error(err.response?.data?.detail || 'Search failed'),
  })

  const isRunning = mut.isPending || (taskStatus && !['SUCCESS', 'FAILURE'].includes(taskStatus))

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Job Search</h1>
        <p className="text-gray-500 mt-1">Search Job Bank Canada, LinkedIn, Indeed, and Glassdoor simultaneously.</p>
      </div>

      <div className="card p-6 space-y-5">
        {/* Keywords */}
        <div>
          <label className="label">Keywords *</label>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              className="input pl-10"
              placeholder="e.g. Python Backend Engineer, React Developer"
              value={form.keywords}
              onChange={set('keywords')}
            />
          </div>
        </div>

        {/* Location */}
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

        {/* Salary range */}
        <div>
          <label className="label">Salary Range (CAD)</label>
          <div className="flex gap-3">
            <div className="relative flex-1">
              <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="number"
                className="input pl-9"
                placeholder="Min (e.g. 120000)"
                value={form.salary_min}
                onChange={set('salary_min')}
              />
            </div>
            <div className="relative flex-1">
              <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="number"
                className="input pl-9"
                placeholder="Max (e.g. 200000)"
                value={form.salary_max}
                onChange={set('salary_max')}
              />
            </div>
          </div>
        </div>

        {/* Job type */}
        <div>
          <label className="label">Job Type</label>
          <div className="flex flex-wrap gap-2">
            {JOB_TYPES.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setForm((f) => ({ ...f, job_type: f.job_type === value ? '' : value }))}
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

        {/* Sources */}
        <div>
          <label className="label">Job Boards</label>
          <div className="flex gap-2">
            {SOURCES.map((s) => (
              <button
                key={s}
                onClick={() => toggleSource(s)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border capitalize transition-all ${
                  form.sources.includes(s)
                    ? 'bg-tomato-600 text-white border-tomato-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-tomato-300'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* Limit */}
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

        {/* Submit */}
        <button
          onClick={() => mut.mutate()}
          disabled={!form.keywords || isRunning}
          className="btn-primary w-full flex items-center justify-center gap-2"
        >
          {isRunning ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Searching… ({taskStatus || 'queued'})
            </>
          ) : (
            <>
              <Search className="w-4 h-4" />
              Search Jobs
            </>
          )}
        </button>

        {taskStatus === 'SUCCESS' && (
          <div className="flex items-center gap-2 text-green-600 text-sm bg-green-50 px-4 py-3 rounded-lg">
            <CheckCircle2 className="w-4 h-4" />
            Search complete! New jobs added to your queue.
          </div>
        )}
      </div>
    </div>
  )
}
