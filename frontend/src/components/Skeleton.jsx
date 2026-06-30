export function SkeletonLine({ className = '' }) {
  return <div className={`animate-pulse bg-gray-200 rounded ${className}`} />
}

export function JobCardSkeleton() {
  return (
    <div className="card p-4">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-gray-200 animate-pulse flex-shrink-0" />
        <div className="flex-1 space-y-2">
          <SkeletonLine className="h-4 w-2/3" />
          <SkeletonLine className="h-3 w-1/3" />
          <div className="flex gap-2 mt-3">
            <SkeletonLine className="h-3 w-24" />
            <SkeletonLine className="h-3 w-20" />
          </div>
        </div>
      </div>
    </div>
  )
}

export function StatCardSkeleton() {
  return (
    <div className="card p-4">
      <SkeletonLine className="h-5 w-5 mb-3" />
      <SkeletonLine className="h-8 w-16 mb-1" />
      <SkeletonLine className="h-3 w-24" />
    </div>
  )
}

export function ApplicationRowSkeleton() {
  return (
    <div className="flex items-center gap-4 p-4">
      <div className="w-10 h-10 rounded-lg bg-gray-200 animate-pulse flex-shrink-0" />
      <div className="flex-1 space-y-2">
        <SkeletonLine className="h-4 w-1/2" />
        <SkeletonLine className="h-3 w-1/3" />
      </div>
      <SkeletonLine className="h-5 w-16 rounded-full" />
    </div>
  )
}
