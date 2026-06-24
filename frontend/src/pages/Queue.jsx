import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import toast from 'react-hot-toast'
import { getJobQueue, approveJob, rejectJob, createApplication } from '../api/client'
import JobCard from '../components/JobCard'
import { CheckCircle2, XCircle, Loader2, ListFilter } from 'lucide-react'

const SWIPE_THRESHOLD = 100

export default function Queue() {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [minScore, setMinScore] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [dragX, setDragX] = useState(0)
  const cardRef = useRef(null)

  const { data, isLoading } = useQuery({
    queryKey: ['jobQueue', { page, min_score: minScore }],
    queryFn: () => getJobQueue({ page, per_page: 10, min_score: minScore }),
    select: (r) => r.data,
  })

  const approveMut = useMutation({
    mutationFn: ({ jobId }) => approveJob(jobId),
    onSuccess: (_, { autoApply, jobId }) => {
      if (autoApply) {
        createApplication({ job_id: jobId })
          .then(() => toast.success('Job approved & application queued!'))
          .catch(() => toast.success('Job approved!'))
      } else {
        toast.success('Job approved and moved to applications.')
      }
      qc.invalidateQueries(['jobQueue'])
      qc.invalidateQueries(['appStats'])
    },
  })

  const rejectMut = useMutation({
    mutationFn: (jobId) => rejectJob(jobId),
    onSuccess: () => {
      toast('Job skipped.')
      qc.invalidateQueries(['jobQueue'])
    },
  })

  const jobs = data?.jobs || []
  const currentJob = jobs[0]

  const handleApprove = (autoApply = false) => {
    if (!currentJob) return
    approveMut.mutate({ jobId: currentJob.id, autoApply })
    setDragX(0)
  }

  const handleReject = () => {
    if (!currentJob) return
    rejectMut.mutate(currentJob.id)
    setDragX(0)
  }

  const swipeColor = dragX > 50 ? 'text-green-500' : dragX < -50 ? 'text-red-500' : 'text-transparent'
  const swipeLabel = dragX > 50 ? 'APPLY' : dragX < -50 ? 'SKIP' : ''

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Job Queue</h1>
          <p className="text-gray-500 mt-1">
            {data?.total ?? 0} jobs waiting — swipe right to apply, left to skip
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ListFilter className="w-4 h-4 text-gray-400" />
          <select
            className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-tomato-500"
            value={minScore}
            onChange={(e) => setMinScore(parseFloat(e.target.value))}
          >
            <option value={0}>All matches</option>
            <option value={0.4}>40%+ match</option>
            <option value={0.6}>60%+ match</option>
            <option value={0.8}>80%+ match</option>
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-tomato-500" />
        </div>
      ) : !jobs.length ? (
        <div className="card p-12 text-center">
          <div className="text-5xl mb-4">🎉</div>
          <h3 className="font-semibold text-gray-900 text-lg">Queue is empty!</h3>
          <p className="text-gray-500 mt-2 text-sm">
            Run a job search to find new matches, or lower the match filter.
          </p>
        </div>
      ) : (
        <div className="relative">
          {/* Stack effect — show 2 cards behind */}
          {jobs.slice(1, 3).reverse().map((job, i) => (
            <div
              key={job.id}
              className="absolute inset-x-0 top-0 pointer-events-none"
              style={{
                transform: `scale(${0.95 - i * 0.03}) translateY(${(i + 1) * 10}px)`,
                zIndex: -1 - i,
                opacity: 0.6 - i * 0.2,
              }}
            >
              <JobCard job={job} />
            </div>
          ))}

          {/* Current card — draggable */}
          <AnimatePresence mode="wait">
            <motion.div
              key={currentJob.id}
              drag="x"
              dragConstraints={{ left: -300, right: 300 }}
              onDrag={(_, info) => setDragX(info.offset.x)}
              onDragEnd={(_, info) => {
                if (info.offset.x > SWIPE_THRESHOLD) handleApprove(true)
                else if (info.offset.x < -SWIPE_THRESHOLD) handleReject()
                else setDragX(0)
              }}
              animate={{ rotate: dragX / 30 }}
              exit={{ x: dragX > 0 ? 500 : -500, opacity: 0, transition: { duration: 0.3 } }}
              className="cursor-grab active:cursor-grabbing select-none"
              whileDrag={{ scale: 1.02 }}
            >
              {/* Swipe indicator overlay */}
              {Math.abs(dragX) > 30 && (
                <div className={`absolute inset-0 flex items-center justify-center z-10 pointer-events-none rounded-xl ${dragX > 0 ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
                  <span className={`text-4xl font-black tracking-widest ${swipeColor}`}>
                    {swipeLabel}
                  </span>
                </div>
              )}
              <JobCard job={currentJob} />
            </motion.div>
          </AnimatePresence>

          {/* Action buttons */}
          <div className="flex items-center justify-center gap-4 mt-6">
            <button
              onClick={handleReject}
              disabled={rejectMut.isPending}
              className="w-14 h-14 rounded-full bg-white border-2 border-red-200 text-red-500 hover:bg-red-50 hover:border-red-400 transition-all flex items-center justify-center shadow-sm"
            >
              <XCircle className="w-7 h-7" />
            </button>
            <button
              onClick={() => handleApprove(false)}
              disabled={approveMut.isPending}
              className="w-14 h-14 rounded-full bg-white border-2 border-yellow-200 text-yellow-600 hover:bg-yellow-50 hover:border-yellow-400 transition-all flex items-center justify-center shadow-sm text-xs font-bold"
            >
              Save
            </button>
            <button
              onClick={() => handleApprove(true)}
              disabled={approveMut.isPending}
              className="w-14 h-14 rounded-full bg-white border-2 border-green-200 text-green-600 hover:bg-green-50 hover:border-green-400 transition-all flex items-center justify-center shadow-sm"
            >
              <CheckCircle2 className="w-7 h-7" />
            </button>
          </div>
          <div className="flex justify-center gap-12 mt-2 text-xs text-gray-400">
            <span>Skip</span>
            <span>Save</span>
            <span>Apply</span>
          </div>
        </div>
      )}

      {/* Remaining list */}
      {jobs.length > 1 && (
        <div className="space-y-3">
          <h2 className="font-medium text-gray-700 text-sm">Coming up ({jobs.length - 1} more)</h2>
          {jobs.slice(1).map((job) => (
            <JobCard
              key={job.id}
              job={job}
              compact
              actions={
                <>
                  <button
                    onClick={() => rejectMut.mutate(job.id)}
                    className="btn-secondary text-xs px-3 py-1.5 text-red-600 border-red-100 hover:bg-red-50"
                  >
                    Skip
                  </button>
                  <button
                    onClick={() => approveMut.mutate({ jobId: job.id, autoApply: true })}
                    className="btn-primary text-xs px-3 py-1.5"
                  >
                    Apply
                  </button>
                </>
              }
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {data?.total > 10 && (
        <div className="flex justify-center gap-3">
          <button
            className="btn-secondary"
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </button>
          <span className="self-center text-sm text-gray-500">
            Page {page} of {Math.ceil(data.total / 10)}
          </span>
          <button
            className="btn-secondary"
            disabled={page * 10 >= data.total}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
