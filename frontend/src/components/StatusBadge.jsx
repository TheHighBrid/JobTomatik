const STATUS_STYLES = {
  pending: 'border-gray-300/40 bg-gray-100 text-gray-600',
  applying: 'border-blue-400/25 bg-blue-500/15 text-blue-200',
  applied: 'border-tomato-400/30 bg-tomato-600/15 text-tomato-300',
  interviewing: 'border-amber-400/30 bg-amber-400/15 text-amber-200',
  offer: 'border-emerald-400/30 bg-emerald-400/15 text-emerald-200',
  rejected: 'border-red-400/30 bg-red-500/15 text-red-200',
  withdrawn: 'border-gray-300/30 bg-gray-100 text-gray-500',
  new: 'border-blue-400/25 bg-blue-500/15 text-blue-200',
  queued: 'border-amber-400/30 bg-amber-400/15 text-amber-200',
  approved: 'border-emerald-400/30 bg-emerald-400/15 text-emerald-200',
  shortlisted: 'border-tomato-400/30 bg-tomato-600/15 text-tomato-300',
  assessment: 'border-amber-400/30 bg-amber-400/15 text-amber-200',
  hired: 'border-emerald-400/30 bg-emerald-400/15 text-emerald-200',
  failed: 'border-red-400/30 bg-red-500/15 text-red-200',
  archived: 'border-gray-300/30 bg-gray-100 text-gray-500',
}

const STATUS_LABELS = {
  pending: 'Pending',
  applying: 'Applying…',
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  new: 'New',
  queued: 'In Queue',
  approved: 'Approved',
  shortlisted: 'Shortlisted',
  assessment: 'Assessment',
  hired: 'Hired',
  failed: 'Failed',
  archived: 'Archived',
}

export default function StatusBadge({ status, className = '' }) {
  return (
    <span className={`badge ${STATUS_STYLES[status] || 'border-gray-300/30 bg-gray-100 text-gray-600'} ${className}`}>
      {STATUS_LABELS[status] || status}
    </span>
  )
}
