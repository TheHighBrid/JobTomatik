import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Loader2, PlusCircle, ShieldCheck } from 'lucide-react'
import api, { getApiErrorMessage } from '../api/client'

const EMPTY = {
  employer: '',
  role: '',
  application_url: '',
  location: '',
}

export default function CurrentLeverTargetForm() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(EMPTY)
  const [expanded, setExpanded] = useState(false)

  const mutation = useMutation({
    mutationFn: () => api.post('/supervised-pilot/lever-candidates', {
      employer: form.employer.trim(),
      role: form.role.trim(),
      application_url: form.application_url.trim(),
      location: form.location.trim() || null,
      notes: 'Owner-selected in JobTomatik current Lever operator UI',
      source_reference: 'current-lever-operator-ui',
    }, {
      // Exact target verification may make two sequential bounded network probes.
      // Do not inherit the global 20s axios timeout and falsely report failure while
      // the backend is still verifying and may commit the exact owner-selected target.
      timeout: 60000,
    }),
    onSuccess: async (response) => {
      const applicationId = response.data?.application_id
      setForm(EMPTY)
      setExpanded(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['current-lever-workspace'] }),
        queryClient.invalidateQueries({ queryKey: ['applications'] }),
        queryClient.invalidateQueries({ queryKey: ['appStats'] }),
      ])
      toast.success(
        applicationId
          ? `Lever target added as application ${applicationId}.`
          : 'Lever target added.',
      )
    },
    onError: (error) => toast.error(
      getApiErrorMessage(error, 'The exact Lever target could not be verified and added.'),
    ),
  })

  const valid = form.employer.trim()
    && form.role.trim()
    && /^https:\/\/jobs\.(?:eu\.)?lever\.co\//i.test(form.application_url.trim())

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="inline-flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-xs font-semibold text-blue-800 hover:bg-blue-100"
      >
        <PlusCircle className="h-4 w-4" /> Add exact Lever target
      </button>
    )
  }

  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
      <div className="flex items-start gap-2">
        <ShieldCheck className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-700" />
        <div>
          <h2 className="text-sm font-semibold text-blue-950">Add an owner-selected Lever application</h2>
          <p className="mt-1 text-xs leading-relaxed text-blue-800">
            JobTomatik verifies the exact Lever posting identity before creating the preparation record. This does not approve or submit the application.
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="text-xs font-medium text-slate-700">
          Employer
          <input
            value={form.employer}
            onChange={(event) => setForm((value) => ({ ...value, employer: event.target.value }))}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500"
            placeholder="Maple"
          />
        </label>
        <label className="text-xs font-medium text-slate-700">
          Role
          <input
            value={form.role}
            onChange={(event) => setForm((value) => ({ ...value, role: event.target.value }))}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500"
            placeholder="Client Success Associate"
          />
        </label>
        <label className="text-xs font-medium text-slate-700 md:col-span-2">
          Exact Lever posting or apply URL
          <input
            value={form.application_url}
            onChange={(event) => setForm((value) => ({ ...value, application_url: event.target.value }))}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500"
            placeholder="https://jobs.lever.co/company/posting-id/apply"
            inputMode="url"
          />
        </label>
        <label className="text-xs font-medium text-slate-700 md:col-span-2">
          Location <span className="font-normal text-slate-400">optional</span>
          <input
            value={form.location}
            onChange={(event) => setForm((value) => ({ ...value, location: event.target.value }))}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500"
            placeholder="Remote within Canada"
          />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!valid || mutation.isPending}
          onClick={() => mutation.mutate()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-700 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <PlusCircle className="h-3.5 w-3.5" />}
          Verify and add target
        </button>
        <button
          type="button"
          disabled={mutation.isPending}
          onClick={() => {
            setForm(EMPTY)
            setExpanded(false)
          }}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
        >
          Cancel
        </button>
      </div>
    </section>
  )
}
