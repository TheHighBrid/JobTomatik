import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Database,
  GitCompareArrows,
  HeartPulse,
  Loader2,
  Network,
  PencilLine,
  RefreshCw,
  Search,
  Sparkles,
  UsersRound,
} from 'lucide-react'

import { getApiErrorMessage } from '../api/client'
import {
  listCareerMemories,
  listKnowledgeNodes,
  listSelectorDiagnostics,
} from '../api/intelligence'
import {
  correctCareerMemory,
  getOperationsWorkspace,
  listOperationsKnowledgeEdges,
} from '../api/operations'

const TABS = [
  { id: 'pipeline', label: 'Pipeline', icon: BriefcaseBusiness },
  { id: 'agenda', label: 'Agenda', icon: CalendarClock },
  { id: 'timeline', label: 'Timeline', icon: Activity },
  { id: 'compare', label: 'Compare', icon: GitCompareArrows },
  { id: 'memory', label: 'Memory', icon: Database },
  { id: 'knowledge', label: 'Knowledge', icon: Network },
  { id: 'selectors', label: 'Selector Health', icon: HeartPulse },
]

function formatDate(value, includeTime = true) {
  if (!value) return 'Not scheduled'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown time'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    ...(includeTime ? { hour: 'numeric', minute: '2-digit' } : {}),
  }).format(date)
}

function statusClass(status) {
  const value = String(status || '').toLowerCase()
  if (['offer', 'completed', 'confirmed', 'sent', 'healthy'].includes(value)) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  }
  if (['interviewing', 'applied', 'approved', 'running', 'submitted'].includes(value)) {
    return 'border-blue-200 bg-blue-50 text-blue-700'
  }
  if (['needs_review', 'needs_recipient', 'blocked', 'delivery_uncertain', 'medium'].includes(value)) {
    return 'border-amber-200 bg-amber-50 text-amber-700'
  }
  if (['rejected', 'failed', 'withdrawn', 'high'].includes(value)) {
    return 'border-red-200 bg-red-50 text-red-700'
  }
  return 'border-gray-200 bg-gray-50 text-gray-600'
}

function Metric({ label, value, detail, icon: Icon }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="brand-icon-well h-9 w-9"><Icon className="h-4 w-4" /></div>
        <div className="text-xl font-bold text-gray-900">{value}</div>
      </div>
      <div className="mt-3 text-sm font-semibold text-gray-900">{label}</div>
      <div className="mt-0.5 text-xs text-gray-500">{detail}</div>
    </div>
  )
}

function EmptyState({ children }) {
  return (
    <div className="rounded-2xl border border-dashed border-gray-300 bg-gray-50/60 p-8 text-center text-sm text-gray-500">
      {children}
    </div>
  )
}

function PipelineView({ columns }) {
  return (
    <div className="overflow-x-auto pb-3">
      <div className="flex min-w-max gap-3">
        {columns.map((column) => (
          <section key={column.status} className="w-[286px] rounded-2xl border border-gray-200 bg-gray-50/80 p-3">
            <div className="flex items-center justify-between gap-2 px-1 pb-3">
              <div className="text-sm font-bold text-gray-900">{column.label}</div>
              <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-gray-500 shadow-sm">
                {column.count}
              </span>
            </div>
            <div className="space-y-2.5">
              {column.items.map((item) => (
                <Link
                  key={item.application_id}
                  to={`/applications/${item.application_id}`}
                  className="block rounded-xl border border-gray-200 bg-white p-3 shadow-sm transition hover:border-tomato-300 hover:shadow-md"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-gray-900">{item.title}</div>
                      <div className="mt-0.5 truncate text-xs text-gray-500">{item.company}</div>
                    </div>
                    <ChevronRight className="h-4 w-4 flex-shrink-0 text-gray-300" />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${statusClass(item.automation_state)}`}>
                      {String(item.automation_state).replaceAll('_', ' ')}
                    </span>
                    {item.open_review_count > 0 && (
                      <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                        {item.open_review_count} review{item.open_review_count === 1 ? '' : 's'}
                      </span>
                    )}
                    {item.followup_count > 0 && (
                      <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-700">
                        {item.followup_count} follow-up{item.followup_count === 1 ? '' : 's'}
                      </span>
                    )}
                  </div>
                  <div className="mt-3 text-[11px] text-gray-400">
                    {item.interview_at
                      ? `Interview ${formatDate(item.interview_at)}`
                      : item.applied_at
                        ? `Applied ${formatDate(item.applied_at, false)}`
                        : item.latest_event_at
                          ? `Updated ${formatDate(item.latest_event_at)}`
                          : 'No dated activity yet'}
                  </div>
                </Link>
              ))}
              {!column.items.length && (
                <div className="rounded-xl border border-dashed border-gray-300 bg-white/60 p-5 text-center text-xs text-gray-400">
                  Empty
                </div>
              )}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}

function AgendaView({ items }) {
  if (!items.length) return <EmptyState>No interviews, reviews, or recruiter follow-ups are due in this window.</EmptyState>
  return (
    <div className="space-y-2.5">
      {items.map((item, index) => (
        <div key={`${item.item_type}-${item.followup_id || item.application_id || item.recruiter_contact_id || index}`} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex items-start gap-3">
            <div className={`mt-0.5 rounded-xl border p-2 ${statusClass(item.priority)}`}>
              {item.overdue ? <AlertTriangle className="h-4 w-4" /> : <CalendarClock className="h-4 w-4" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-sm font-semibold text-gray-900">{item.title}</div>
                {item.overdue && <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-bold text-red-600">OVERDUE</span>}
              </div>
              {item.subtitle && <div className="mt-0.5 text-xs text-gray-500">{item.subtitle}</div>}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                <span className="font-semibold text-gray-700">{formatDate(item.scheduled_at)}</span>
                <span>•</span>
                <span className="capitalize">{item.item_type.replaceAll('_', ' ')}</span>
                <span>•</span>
                <span className="capitalize">{String(item.status).replaceAll('_', ' ')}</span>
              </div>
            </div>
            {item.action_url && (
              <Link to={item.action_url} className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700" aria-label={`Open ${item.title}`}>
                <ArrowRight className="h-4 w-4" />
              </Link>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function TimelineView({ items }) {
  if (!items.length) return <EmptyState>No application or recruiter activity has been recorded yet.</EmptyState>
  return (
    <div className="relative ml-2 space-y-0 border-l border-gray-200 pl-5">
      {items.map((item, index) => (
        <div key={`${item.kind}-${item.occurred_at}-${index}`} className="relative pb-5">
          <span className="absolute -left-[25px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-tomato-500 shadow" />
          <div className="rounded-xl border border-gray-200 bg-white p-3.5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="text-sm font-semibold text-gray-900">{item.title}</div>
                <div className="mt-0.5 text-xs text-gray-500">
                  {[item.company, item.summary].filter(Boolean).join(' · ')}
                </div>
              </div>
              <div className="text-[11px] font-medium text-gray-400">{formatDate(item.occurred_at)}</div>
            </div>
            {(item.from_state || item.to_state) && (
              <div className="mt-2 text-[11px] text-gray-500">
                {[item.from_state, item.to_state].filter(Boolean).join(' → ')}
              </div>
            )}
            {item.action_url && (
              <Link to={item.action_url} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-tomato-600 hover:underline">
                Open record <ChevronRight className="h-3 w-3" />
              </Link>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function ComparisonView({ items }) {
  const dimensions = useMemo(() => {
    const keys = new Set()
    items.forEach((item) => Object.keys(item.dimension_scores || {}).forEach((key) => keys.add(key)))
    return [...keys]
  }, [items])

  if (!items.length) return <EmptyState>No structured opportunity evaluations are available to compare yet.</EmptyState>
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-2xl border border-gray-200 bg-white shadow-sm">
        <table className="min-w-[900px] w-full text-left text-xs">
          <thead className="border-b border-gray-200 bg-gray-50 text-gray-500">
            <tr>
              <th className="px-4 py-3 font-semibold">Opportunity</th>
              <th className="px-3 py-3 font-semibold">Score</th>
              <th className="px-3 py-3 font-semibold">Recommendation</th>
              <th className="px-3 py-3 font-semibold">Legitimacy</th>
              {dimensions.map((dimension) => (
                <th key={dimension} className="px-3 py-3 font-semibold capitalize">{dimension.replaceAll('_', ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map((item) => (
              <tr key={item.evaluation_id} className="align-top">
                <td className="px-4 py-3">
                  <div className="font-semibold text-gray-900">{item.title}</div>
                  <div className="mt-0.5 text-gray-500">{item.company}</div>
                  {!!item.hard_blockers?.length && (
                    <div className="mt-1 text-[10px] font-semibold text-red-600">{item.hard_blockers.length} blocker{item.hard_blockers.length === 1 ? '' : 's'}</div>
                  )}
                </td>
                <td className="px-3 py-3 text-base font-bold text-gray-900">{Number(item.weighted_score).toFixed(2)}</td>
                <td className="px-3 py-3"><span className={`rounded-full border px-2 py-1 font-semibold ${statusClass(item.recommendation)}`}>{item.recommendation}</span></td>
                <td className="px-3 py-3 capitalize text-gray-600">{String(item.legitimacy_status).replaceAll('_', ' ')}</td>
                {dimensions.map((dimension) => (
                  <td key={dimension} className="px-3 py-3 font-semibold text-gray-700">
                    {item.dimension_scores?.[dimension] ?? '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500">Scores are comparison aids only. Hard blockers and legitimacy remain separate from the weighted fit score.</p>
    </div>
  )
}

function MemoryView({ memories, onCorrect, isSaving }) {
  const [selectedId, setSelectedId] = useState(null)
  const selected = memories.find((memory) => memory.id === selectedId) || memories[0] || null
  const [draft, setDraft] = useState(null)

  const selectMemory = (memory) => {
    setSelectedId(memory.id)
    setDraft({ content: memory.content, confidence: String(memory.confidence), is_active: memory.is_active })
  }

  const editor = draft || (selected
    ? { content: selected.content, confidence: String(selected.confidence), is_active: selected.is_active }
    : null)

  if (!memories.length) return <EmptyState>No career memory records are available yet.</EmptyState>

  return (
    <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
      <div className="space-y-2 max-h-[620px] overflow-y-auto pr-1">
        {memories.map((memory) => (
          <button
            type="button"
            key={memory.id}
            onClick={() => selectMemory(memory)}
            className={`w-full rounded-xl border p-3 text-left transition ${selected?.id === memory.id ? 'border-tomato-300 bg-tomato-50/60' : 'border-gray-200 bg-white hover:border-gray-300'}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-gray-900">{memory.key}</div>
                <div className="mt-0.5 text-[11px] uppercase tracking-wide text-gray-400">{memory.kind} · {memory.source}</div>
              </div>
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${memory.is_active ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-gray-200 bg-gray-100 text-gray-500'}`}>
                {memory.is_active ? 'active' : 'inactive'}
              </span>
            </div>
            <div className="mt-2 line-clamp-2 text-xs text-gray-600">{memory.content}</div>
          </button>
        ))}
      </div>

      {selected && editor && (
        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <PencilLine className="h-4 w-4 text-tomato-600" />
            <h3 className="font-bold text-gray-900">Review memory #{selected.id}</h3>
          </div>
          <p className="mt-1 text-xs text-gray-500">Corrections preserve the previous value in bounded provenance history and mark the record as user-corrected.</p>

          <label className="mt-4 block text-xs font-semibold text-gray-700">Content</label>
          <textarea
            value={editor.content}
            onChange={(event) => setDraft({ ...editor, content: event.target.value })}
            rows={6}
            className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-tomato-400"
          />

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-semibold text-gray-700">
              Confidence
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={editor.confidence}
                onChange={(event) => setDraft({ ...editor, confidence: event.target.value })}
                className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-tomato-400"
              />
            </label>
            <label className="text-xs font-semibold text-gray-700">
              Record state
              <select
                value={editor.is_active ? 'active' : 'inactive'}
                onChange={(event) => setDraft({ ...editor, is_active: event.target.value === 'active' })}
                className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-tomato-400"
              >
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </label>
          </div>

          <div className="mt-4 rounded-xl bg-gray-50 p-3 text-[11px] text-gray-500">
            Source: <span className="font-semibold text-gray-700">{selected.source}</span>
            {selected.source_ref ? ` · ${selected.source_ref}` : ''}
          </div>

          <button
            type="button"
            disabled={isSaving || !editor.content.trim() || Number.isNaN(Number(editor.confidence))}
            onClick={() => onCorrect(selected.id, {
              content: editor.content.trim(),
              confidence: Math.max(0, Math.min(1, Number(editor.confidence))),
              is_active: editor.is_active,
            })}
            className="mt-4 inline-flex items-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            Save correction
          </button>
        </div>
      )}
    </div>
  )
}

function KnowledgeView({ nodes, edges }) {
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(null)
  const nodeTypes = useMemo(() => [...new Set(nodes.map((node) => node.node_type))].sort(), [nodes])
  const filtered = useMemo(() => nodes.filter((node) => {
    const matchesQuery = !query || node.label.toLowerCase().includes(query.toLowerCase())
    const matchesType = typeFilter === 'all' || node.node_type === typeFilter
    return matchesQuery && matchesType
  }), [nodes, query, typeFilter])
  const selected = nodes.find((node) => node.id === selectedId) || filtered[0] || null
  const nodeLookup = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes])
  const connected = selected
    ? edges.filter((edge) => edge.from_node_id === selected.id || edge.to_node_id === selected.id)
    : []

  if (!nodes.length) return <EmptyState>No knowledge graph nodes are available yet.</EmptyState>
  return (
    <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
      <div>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search knowledge" className="w-full rounded-xl border border-gray-200 py-2 pl-9 pr-3 text-sm outline-none focus:border-tomato-400" />
          </div>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="rounded-xl border border-gray-200 px-3 py-2 text-sm outline-none focus:border-tomato-400">
            <option value="all">All types</option>
            {nodeTypes.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </div>
        <div className="mt-3 space-y-2 max-h-[570px] overflow-y-auto pr-1">
          {filtered.map((node) => (
            <button key={node.id} type="button" onClick={() => setSelectedId(node.id)} className={`w-full rounded-xl border p-3 text-left transition ${selected?.id === node.id ? 'border-blue-300 bg-blue-50/60' : 'border-gray-200 bg-white hover:border-gray-300'}`}>
              <div className="flex items-center justify-between gap-3">
                <div className="truncate text-sm font-semibold text-gray-900">{node.label}</div>
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-semibold text-gray-500">{node.node_type}</span>
              </div>
              <div className="mt-1 text-[11px] text-gray-400">Confidence {Math.round(Number(node.confidence || 0) * 100)}%</div>
            </button>
          ))}
        </div>
      </div>

      {selected && (
        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.12em] text-blue-600">{selected.node_type}</div>
              <h3 className="mt-1 text-lg font-bold text-gray-900">{selected.label}</h3>
            </div>
            <Network className="h-5 w-5 text-gray-300" />
          </div>
          {selected.source_url && <div className="mt-2 break-all text-[11px] text-gray-400">{selected.source_url}</div>}

          <div className="mt-4">
            <div className="text-xs font-semibold uppercase tracking-[0.12em] text-gray-400">Connected evidence</div>
            <div className="mt-2 space-y-2">
              {connected.map((edge) => {
                const outgoing = edge.from_node_id === selected.id
                const peer = nodeLookup[outgoing ? edge.to_node_id : edge.from_node_id]
                return (
                  <div key={edge.id} className="rounded-xl bg-gray-50 p-3">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-semibold text-gray-900">{outgoing ? selected.label : peer?.label || `Node ${edge.from_node_id}`}</span>
                      <ArrowRight className="h-3 w-3 text-gray-400" />
                      <span className="font-semibold text-blue-700">{edge.relation.replaceAll('_', ' ')}</span>
                      <ArrowRight className="h-3 w-3 text-gray-400" />
                      <span className="font-semibold text-gray-900">{outgoing ? peer?.label || `Node ${edge.to_node_id}` : selected.label}</span>
                    </div>
                    <div className="mt-1 text-[11px] text-gray-400">Weight {Number(edge.weight).toFixed(2)}</div>
                  </div>
                )
              })}
              {!connected.length && <div className="rounded-xl border border-dashed border-gray-300 p-5 text-center text-xs text-gray-400">No edges connected to this node.</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function SelectorView({ selectors }) {
  const ordered = [...selectors].sort((a, b) => Number(a.health_score || 0) - Number(b.health_score || 0))
  if (!ordered.length) return <EmptyState>No selector diagnostics are recorded yet.</EmptyState>
  return (
    <div className="space-y-2.5">
      {ordered.map((selector) => {
        const health = Math.round(Number(selector.health_score || 0) * 100)
        return (
          <div key={selector.id} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">{selector.platform}</span>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-semibold text-gray-500">{selector.intent}</span>
                  {selector.is_disabled && <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-600">disabled</span>}
                </div>
                <div className="mt-1 truncate font-mono text-[11px] text-gray-500">{selector.selector}</div>
                <div className="mt-1 text-[11px] text-gray-400">{selector.page_signature}</div>
              </div>
              <div className={`rounded-xl border px-3 py-1.5 text-sm font-bold ${health >= 65 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : health >= 40 ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-red-200 bg-red-50 text-red-700'}`}>
                {health}%
              </div>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-gray-100">
              <div className="h-full rounded-full bg-gray-700" style={{ width: `${Math.max(0, Math.min(100, health))}%` }} />
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-gray-500">
              <span>{selector.success_count} successes</span>
              <span>{selector.failure_count} failures</span>
              {selector.last_failure_at && <span>Last failure {formatDate(selector.last_failure_at)}</span>}
            </div>
            {selector.last_failure_reason && (
              <div className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{selector.last_failure_reason}</div>
            )}
          </div>
        )
      })}
      <Link to="/execution" className="inline-flex items-center gap-1 text-xs font-semibold text-tomato-600 hover:underline">
        Open Execution Center for selector controls <ChevronRight className="h-3 w-3" />
      </Link>
    </div>
  )
}

export default function OperationsCenter() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('pipeline')
  const [notice, setNotice] = useState(null)

  const workspaceQuery = useQuery({
    queryKey: ['operationsWorkspace'],
    queryFn: () => getOperationsWorkspace({ agenda_days: 14, timeline_limit: 120, evaluation_limit: 25 }),
    select: (response) => response.data,
    refetchInterval: 30_000,
  })
  const memoriesQuery = useQuery({
    queryKey: ['careerMemories', 'operations'],
    queryFn: () => listCareerMemories({ active_only: false }),
    select: (response) => response.data,
  })
  const nodesQuery = useQuery({
    queryKey: ['knowledgeNodes', 'operations'],
    queryFn: () => listKnowledgeNodes(),
    select: (response) => response.data,
  })
  const edgesQuery = useQuery({
    queryKey: ['knowledgeEdges', 'operations'],
    queryFn: () => listOperationsKnowledgeEdges(),
    select: (response) => response.data,
  })
  const selectorsQuery = useQuery({
    queryKey: ['selectorDiagnostics', 'operations'],
    queryFn: () => listSelectorDiagnostics(),
    select: (response) => response.data,
  })

  const correctMemory = useMutation({
    mutationFn: ({ memoryId, data }) => correctCareerMemory(memoryId, data),
    onSuccess: () => {
      setNotice('Career memory corrected. Previous provenance was retained.')
      queryClient.invalidateQueries({ queryKey: ['careerMemories'] })
      queryClient.invalidateQueries({ queryKey: ['operationsWorkspace'] })
    },
    onError: (error) => setNotice(getApiErrorMessage(error, 'Could not correct career memory.')),
  })

  const workspace = workspaceQuery.data
  const loading = workspaceQuery.isLoading
  const error = workspaceQuery.error
  const summary = workspace?.summary || {}

  const metrics = [
    { label: 'Active applications', value: summary.active_applications ?? 0, detail: `${summary.applications ?? 0} total records`, icon: BriefcaseBusiness },
    { label: 'Interviews', value: summary.interviewing ?? 0, detail: 'Current interview-stage applications', icon: UsersRound },
    { label: 'Offers', value: summary.offers ?? 0, detail: 'Current offer-stage applications', icon: Sparkles },
    { label: 'Agenda pressure', value: summary.overdue_agenda_items ?? 0, detail: `${summary.agenda_items ?? 0} items in the 14-day window`, icon: CalendarClock },
  ]

  const activeTab = TABS.find((item) => item.id === tab)

  return (
    <div className="space-y-5 animate-fade-in pb-24 md:pb-8">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-tomato-600">
            <CircleDot className="h-4 w-4" />
            Phase 7 operations UX
          </div>
          <h1 className="mt-2 text-xl font-bold text-gray-900 md:text-2xl">Operations Center</h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-500">
            One operational view of applications, interviews, recruiter relationships, evaluations, memory, knowledge, and automation health.
          </p>
        </div>
        <button
          type="button"
          onClick={() => workspaceQuery.refetch()}
          disabled={workspaceQuery.isFetching}
          className="btn-secondary inline-flex items-center justify-center gap-2 text-sm"
        >
          <RefreshCw className={`h-4 w-4 ${workspaceQuery.isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs text-emerald-800">
        Operations Center is an inspect-and-correct layer. It does not grant application submission or recruiter outreach permission.
      </div>

      {notice && <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">{notice}</div>}
      {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{getApiErrorMessage(error, 'Could not load Operations Center.')}</div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {metrics.map((metric) => <Metric key={metric.label} {...metric} value={loading ? '…' : metric.value} />)}
      </div>

      <div className="flex gap-1.5 overflow-x-auto -mx-4 px-4 pb-1 md:mx-0 md:px-0" role="tablist" aria-label="Operations views">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            type="button"
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`inline-flex flex-shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition ${tab === id ? 'bg-gray-900 text-white shadow-sm' : 'border border-gray-200 bg-white text-gray-600 hover:border-gray-300'}`}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      <section aria-label={activeTab?.label || 'Operations view'}>
        {loading && ['pipeline', 'agenda', 'timeline', 'compare'].includes(tab) ? (
          <div className="flex items-center justify-center rounded-2xl border border-gray-200 bg-white p-12 text-sm text-gray-500">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading operations data…
          </div>
        ) : (
          <>
            {tab === 'pipeline' && <PipelineView columns={workspace?.pipeline || []} />}
            {tab === 'agenda' && <AgendaView items={workspace?.agenda || []} />}
            {tab === 'timeline' && <TimelineView items={workspace?.timeline || []} />}
            {tab === 'compare' && <ComparisonView items={workspace?.evaluations || []} />}
            {tab === 'memory' && <MemoryView memories={memoriesQuery.data || []} isSaving={correctMemory.isPending} onCorrect={(memoryId, data) => correctMemory.mutate({ memoryId, data })} />}
            {tab === 'knowledge' && <KnowledgeView nodes={nodesQuery.data || []} edges={edgesQuery.data || []} />}
            {tab === 'selectors' && <SelectorView selectors={selectorsQuery.data || []} />}
          </>
        )}
      </section>
    </div>
  )
}
