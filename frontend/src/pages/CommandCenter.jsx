import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  ContactRound,
  Database,
  Loader2,
  Network,
  Play,
  ShieldCheck,
  Wrench,
} from 'lucide-react'

import { createAgentRun, getIntelligenceOverview } from '../api/client'
import { getApiErrorMessage } from '../api/client'

function MetricCard({ icon: Icon, label, value, detail }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="brand-icon-well h-10 w-10">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
        <div className="text-2xl font-bold text-gray-900">{value}</div>
      </div>
      <div className="mt-3 text-sm font-semibold text-gray-900">{label}</div>
      <div className="mt-0.5 text-xs text-gray-500">{detail}</div>
    </div>
  )
}

function statusClass(status) {
  if (status === 'completed') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (status === 'failed') return 'bg-red-50 text-red-700 border-red-200'
  if (status === 'blocked') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (status === 'running') return 'bg-blue-50 text-blue-700 border-blue-200'
  return 'bg-gray-50 text-gray-600 border-gray-200'
}

function formatDate(value) {
  if (!value) return 'Not scheduled'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value))
}

export default function CommandCenter() {
  const queryClient = useQueryClient()
  const [objective, setObjective] = useState(
    'Find, evaluate, and prepare the strongest matching role, then plan recruiter follow-up.'
  )
  const [message, setMessage] = useState(null)

  const { data: overview, isLoading } = useQuery({
    queryKey: ['intelligenceOverview'],
    queryFn: () => getIntelligenceOverview(),
    select: (response) => response.data,
    refetchInterval: 30_000,
  })

  const createRun = useMutation({
    mutationFn: () => createAgentRun({ objective, autonomy_level: 'reviewed', run_context: {} }),
    onSuccess: (response) => {
      const run = response.data
      setMessage(`Run #${run.id} planned with ${run.tasks.length} specialist tasks.`)
      queryClient.invalidateQueries({ queryKey: ['intelligenceOverview'] })
    },
    onError: (error) => setMessage(getApiErrorMessage(error, 'Could not create the agent run.')),
  })

  const selectorHealth = overview?.selector_strategies
    ? Math.round((overview.healthy_selectors / overview.selector_strategies) * 100)
    : 0

  const metrics = [
    {
      icon: Database,
      label: 'Persistent memory',
      value: overview?.memories ?? 0,
      detail: 'Verified facts, preferences, outcomes, and proof points',
    },
    {
      icon: ContactRound,
      label: 'Recruiter CRM',
      value: overview?.recruiter_contacts ?? 0,
      detail: `${overview?.followups_due ?? 0} follow-ups currently due`,
    },
    {
      icon: Network,
      label: 'Knowledge graph',
      value: overview?.knowledge_nodes ?? 0,
      detail: `${overview?.knowledge_edges ?? 0} evidence-backed relationships`,
    },
    {
      icon: Wrench,
      label: 'Selector health',
      value: `${selectorHealth}%`,
      detail: `${overview?.healthy_selectors ?? 0} healthy automation strategies`,
    },
  ]

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-tomato-600">
          <BrainCircuit className="h-4 w-4" aria-hidden="true" />
          JobTomatik intelligence layer
        </div>
        <h1 className="mt-2 text-xl md:text-2xl font-bold text-gray-900">Command Center</h1>
        <p className="mt-1 max-w-3xl text-sm text-gray-500">
          Persistent career memory, recruiter relationships, company knowledge, selector learning,
          and observable multi-agent plans around the existing evidence-backed application engine.
        </p>
      </div>

      <div className="rounded-2xl bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950 p-5 text-white shadow-lg">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-300" aria-hidden="true" />
              <h2 className="font-bold">Plan an adaptive agent run</h2>
            </div>
            <p className="mt-1 text-xs text-white/60">
              Planning is separate from execution. Submission policy, approval, adapter maturity,
              idempotency, and confirmation evidence remain authoritative.
            </p>
            <textarea
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              rows={3}
              className="mt-3 w-full rounded-xl border border-white/15 bg-white/10 px-3 py-2.5 text-sm text-white outline-none placeholder:text-white/40 focus:border-tomato-400"
              placeholder="Describe the outcome you want..."
            />
          </div>
          <button
            type="button"
            onClick={() => createRun.mutate()}
            disabled={createRun.isPending || objective.trim().length < 3}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-slate-100 disabled:opacity-50"
          >
            {createRun.isPending
              ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              : <Play className="h-4 w-4" aria-hidden="true" />}
            Build plan
          </button>
        </div>
        {message && <div className="mt-3 rounded-lg bg-white/10 px-3 py-2 text-xs text-white/80">{message}</div>}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {metrics.map((metric) => (
          <MetricCard key={metric.label} {...metric} value={isLoading ? '…' : metric.value} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-bold text-gray-900">Recent agent runs</h2>
              <p className="mt-0.5 text-xs text-gray-500">Plans remain inspectable before any bounded execution.</p>
            </div>
            <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-500">
              <Activity className="h-4 w-4" aria-hidden="true" />
              {overview?.active_agent_runs ?? 0} active
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {(overview?.recent_runs || []).map((run) => (
              <div key={run.id} className="rounded-xl border border-gray-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-gray-900">Run #{run.id}</div>
                    <div className="mt-1 line-clamp-2 text-xs text-gray-500">{run.objective}</div>
                  </div>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass(run.status)}`}>
                    {run.status}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-500">
                  <span>{run.tasks.length} tasks</span>
                  <span>•</span>
                  <span>{run.risk_level} risk</span>
                  <span>•</span>
                  <span>{run.requires_approval ? 'Approval required' : 'Bounded autonomous'}</span>
                </div>
              </div>
            ))}
            {!isLoading && !(overview?.recent_runs || []).length && (
              <div className="rounded-xl border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
                No agent plans yet. Create the first one above.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <Clock3 className="h-5 w-5 text-tomato-600" aria-hidden="true" />
            <div>
              <h2 className="font-bold text-gray-900">Recruiter follow-ups</h2>
              <p className="mt-0.5 text-xs text-gray-500">Relationship actions ordered by due date.</p>
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {(overview?.upcoming_followups || []).map((contact) => (
              <div key={contact.id} className="rounded-xl bg-gray-50 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-gray-900">{contact.full_name}</div>
                    <div className="text-xs text-gray-500">{contact.company}</div>
                  </div>
                  <CheckCircle2 className="h-4 w-4 text-gray-300" aria-hidden="true" />
                </div>
                <div className="mt-2 text-[11px] font-semibold text-tomato-600">
                  {formatDate(contact.next_followup_at)}
                </div>
              </div>
            ))}
            {!isLoading && !(overview?.upcoming_followups || []).length && (
              <div className="rounded-xl border border-dashed border-gray-300 p-5 text-center text-xs text-gray-500">
                No recruiter follow-ups scheduled.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
