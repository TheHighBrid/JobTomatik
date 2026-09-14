import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ExternalLink } from 'lucide-react'
import api from '../api/client'

const LOCAL_RUNTIME_UI_ORIGIN = 'http://127.0.0.1:3000'

function normalizedRevision(value) {
  const revision = String(value || '').trim().toLowerCase()
  return /^[0-9a-f]{7,64}$/.test(revision) ? revision : ''
}

function shortRevision(value) {
  const revision = normalizedRevision(value)
  return revision ? revision.slice(0, 12) : 'unknown'
}

export function runtimeUiRevisionState({ uiRevision, runtimeRevision, origin }) {
  const ui = normalizedRevision(uiRevision)
  const runtime = normalizedRevision(runtimeRevision)
  const mismatch = Boolean(ui && runtime && ui !== runtime)
  const localRuntimeUi = String(origin || '').replace(/\/$/, '') === LOCAL_RUNTIME_UI_ORIGIN
  return {
    ui,
    runtime,
    mismatch,
    localRuntimeUi,
  }
}

export default function RuntimeUiRevisionBoundary() {
  const uiRevision = import.meta.env.VITE_JOBTOMATIK_RUNTIME_REVISION
  const identityQuery = useQuery({
    queryKey: ['runtime-ui-revision-identity'],
    queryFn: () => api.get('/system/runtime-identity'),
    select: (response) => response.data,
    retry: 1,
    refetchInterval: 15000,
  })

  const state = runtimeUiRevisionState({
    uiRevision,
    runtimeRevision: identityQuery.data?.revision,
    origin: window.location.origin,
  })

  if (!state.mismatch) return null

  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`
  const currentRuntimeUiUrl = `${LOCAL_RUNTIME_UI_ORIGIN}${currentPath}`

  return (
    <div
      className="border-b border-amber-300 bg-amber-50 px-4 py-3 text-amber-950"
      data-testid="runtime-ui-revision-mismatch"
      role="alert"
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-2.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-700" />
          <div className="min-w-0 text-xs leading-relaxed">
            <div className="font-semibold">This screen is older than the running JobTomatik runtime.</div>
            <div className="mt-0.5 text-amber-800">
              UI {shortRevision(state.ui)} · runtime {shortRevision(state.runtime)}. The Termux runtime updater updates the backend and current local web UI; it cannot replace JavaScript embedded inside an already-installed APK.
            </div>
          </div>
        </div>
        {!state.localRuntimeUi && (
          <a
            href={currentRuntimeUiUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex flex-shrink-0 items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-100"
          >
            Open current runtime UI
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
    </div>
  )
}
