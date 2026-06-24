import { MapPin, DollarSign, Briefcase, ExternalLink, Building2 } from 'lucide-react'
import StatusBadge from './StatusBadge'

function formatSalary(min, max, currency = 'USD') {
  const fmt = (n) => n >= 1000 ? `$${(n / 1000).toFixed(0)}K` : `$${n}`
  if (min && max) return `${fmt(min)} – ${fmt(max)}`
  if (min) return `${fmt(min)}+`
  if (max) return `Up to ${fmt(max)}`
  return null
}

export default function JobCard({ job, actions, compact = false }) {
  const salary = formatSalary(job.salary_min, job.salary_max, job.salary_currency)

  return (
    <div className="card p-4 hover:shadow-md transition-shadow duration-150">
      <div className="flex items-start gap-3">
        {/* Company avatar */}
        <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-tomato-100 to-tomato-200 flex items-center justify-center text-tomato-700 font-bold text-sm flex-shrink-0">
          {(job.company || '?')[0].toUpperCase()}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="font-semibold text-gray-900 text-sm leading-tight truncate">
                {job.title}
              </h3>
              <div className="flex items-center gap-1.5 mt-0.5 text-gray-500 text-xs">
                <Building2 className="w-3 h-3 flex-shrink-0" />
                <span className="truncate">{job.company}</span>
              </div>
            </div>
            <StatusBadge status={job.status} className="flex-shrink-0" />
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-xs text-gray-500">
            {job.location && (
              <span className="flex items-center gap-1">
                <MapPin className="w-3 h-3" /> {job.location}
              </span>
            )}
            {salary && (
              <span className="flex items-center gap-1">
                <DollarSign className="w-3 h-3" /> {salary}
              </span>
            )}
            {job.job_type && (
              <span className="flex items-center gap-1">
                <Briefcase className="w-3 h-3" /> {job.job_type.replace('_', ' ')}
              </span>
            )}
            {job.source && (
              <span className="capitalize text-gray-400">{job.source}</span>
            )}
          </div>

          {!compact && job.skills?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {job.skills.slice(0, 6).map((s) => (
                <span key={s} className="badge bg-gray-100 text-gray-600 text-[10px]">{s}</span>
              ))}
              {job.skills.length > 6 && (
                <span className="badge bg-gray-100 text-gray-400 text-[10px]">+{job.skills.length - 6}</span>
              )}
            </div>
          )}

          {job.relevance_score != null && (
            <div className="mt-2 flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-tomato-500 rounded-full"
                  style={{ width: `${Math.round(job.relevance_score * 100)}%` }}
                />
              </div>
              <span className="text-xs text-gray-400">
                {Math.round(job.relevance_score * 100)}% match
              </span>
            </div>
          )}
        </div>

        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1.5 text-gray-400 hover:text-tomato-600 transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
          </a>
        )}
      </div>

      {!compact && job.description && (
        <p className="mt-3 text-xs text-gray-500 line-clamp-3 leading-relaxed">
          {job.description}
        </p>
      )}

      {actions && <div className="mt-3 flex gap-2">{actions}</div>}
    </div>
  )
}
