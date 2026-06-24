const STATUS_STYLES = {
  pending: 'bg-gray-100 text-gray-600',
  applying: 'bg-blue-100 text-blue-700',
  applied: 'bg-indigo-100 text-indigo-700',
  interviewing: 'bg-purple-100 text-purple-700',
  offer: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-600',
  withdrawn: 'bg-gray-100 text-gray-500',
  // Job statuses
  new: 'bg-gray-100 text-gray-600',
  queued: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
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
}

export default function StatusBadge({ status, className = '' }) {
  return (
    <span className={`badge ${STATUS_STYLES[status] || 'bg-gray-100 text-gray-600'} ${className}`}>
      {STATUS_LABELS[status] || status}
    </span>
  )
}
