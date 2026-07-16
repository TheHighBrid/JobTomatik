import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { AlertTriangle, CheckCircle2, Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react'

import {
  createAnswerPolicy,
  deleteAnswerPolicy,
  getAnswerPolicyCatalog,
  getApiErrorMessage,
  listAnswerPolicies,
  updateAnswerPolicy,
} from '../api/client'

const initialForm = {
  canonical_key: 'work_authorization',
  mode: 'answer',
  answer_value: '',
  scope: 'global',
  scope_value: '',
  allow_autofill: false,
}

function sensitivityClass(value) {
  if (value === 'legal') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (value === 'sensitive') return 'bg-purple-50 text-purple-700 border-purple-200'
  return 'bg-gray-50 text-gray-600 border-gray-200'
}

export default function AnswerPolicyVault() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialForm)

  const catalogQuery = useQuery({
    queryKey: ['answer-policy-catalog'],
    queryFn: () => getAnswerPolicyCatalog(),
    select: (response) => response.data,
  })

  const policiesQuery = useQuery({
    queryKey: ['answer-policies'],
    queryFn: () => listAnswerPolicies(),
    select: (response) => response.data,
  })

  const catalogByKey = useMemo(
    () => Object.fromEntries((catalogQuery.data || []).map((item) => [item.canonical_key, item])),
    [catalogQuery.data]
  )

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['answer-policies'] })

  const createMutation = useMutation({
    mutationFn: (payload) => createAnswerPolicy(payload),
    onSuccess: () => {
      toast.success('Answer policy saved')
      setForm(initialForm)
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not save answer policy')),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => updateAnswerPolicy(id, data),
    onSuccess: invalidate,
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not update answer policy')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => deleteAnswerPolicy(id),
    onSuccess: () => {
      toast.success('Answer policy deleted')
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not delete answer policy')),
  })

  const selectedCatalog = catalogByKey[form.canonical_key]
  const answerRequired = ['answer', 'decline'].includes(form.mode)
  const scopeValueRequired = form.scope !== 'global'

  const submit = (event) => {
    event.preventDefault()
    const allowAutofill = answerRequired && form.allow_autofill
    createMutation.mutate({
      canonical_key: form.canonical_key,
      mode: form.mode,
      answer_value: answerRequired ? form.answer_value.trim() : null,
      answer_label: answerRequired ? form.answer_value.trim() : null,
      scope: form.scope,
      scope_value: scopeValueRequired ? form.scope_value.trim() : '',
      allow_autofill: allowAutofill,
      confirmed: allowAutofill,
      is_active: true,
    })
  }

  if (catalogQuery.isLoading || policiesQuery.isLoading) {
    return <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-tomato-500" /></div>
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
        <div className="flex gap-3">
          <ShieldCheck className="w-5 h-5 text-amber-700 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-amber-900">No guessed legal or demographic answers</p>
            <p className="text-xs text-amber-800 mt-1">
              Answers are encrypted on the server. A policy is used automatically only after you explicitly
              authorize it. Required questions without an approved policy stop the application for review.
            </p>
          </div>
        </div>
      </div>

      <form onSubmit={submit} className="space-y-4 rounded-xl border border-gray-200 p-4">
        <div>
          <label className="label">Application question</label>
          <select
            className="input w-full"
            value={form.canonical_key}
            onChange={(event) => setForm((current) => ({ ...current, canonical_key: event.target.value }))}
          >
            {(catalogQuery.data || []).map((item) => (
              <option key={item.canonical_key} value={item.canonical_key}>{item.label}</option>
            ))}
          </select>
          {selectedCatalog && (
            <div className="flex items-center gap-2 mt-2">
              <span className={`text-[10px] uppercase tracking-wide border rounded-full px-2 py-0.5 ${sensitivityClass(selectedCatalog.sensitivity)}`}>
                {selectedCatalog.sensitivity}
              </span>
              <span className="text-xs text-gray-500">{selectedCatalog.description}</span>
            </div>
          )}
        </div>

        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="label">Policy</label>
            <select
              className="input w-full"
              value={form.mode}
              onChange={(event) => setForm((current) => ({
                ...current,
                mode: event.target.value,
                allow_autofill: ['answer', 'decline'].includes(event.target.value)
                  ? current.allow_autofill
                  : false,
              }))}
            >
              <option value="answer">Use this answer</option>
              <option value="decline">Use a decline/prefer-not answer</option>
              <option value="ask_each_time">Ask me every time</option>
              <option value="skip">Never answer automatically</option>
            </select>
          </div>

          <div>
            <label className="label">Scope</label>
            <select
              className="input w-full"
              value={form.scope}
              onChange={(event) => setForm((current) => ({ ...current, scope: event.target.value, scope_value: '' }))}
            >
              <option value="global">All applications</option>
              <option value="platform">One platform/domain</option>
              <option value="company">One company</option>
            </select>
          </div>
        </div>

        {scopeValueRequired && (
          <div>
            <label className="label">{form.scope === 'platform' ? 'Platform domain' : 'Company name'}</label>
            <input
              className="input w-full"
              required
              placeholder={form.scope === 'platform' ? 'greenhouse.io' : 'Example Company'}
              value={form.scope_value}
              onChange={(event) => setForm((current) => ({ ...current, scope_value: event.target.value }))}
            />
          </div>
        )}

        {answerRequired && (
          <div>
            <label className="label">Exact answer or option label</label>
            <input
              className="input w-full"
              required
              placeholder="Example: Yes, No, Prefer not to answer, 90,000 CAD"
              value={form.answer_value}
              onChange={(event) => setForm((current) => ({ ...current, answer_value: event.target.value }))}
            />
            <p className="text-[11px] text-gray-500 mt-1">
              Use wording that appears in the application dropdown or choice list whenever possible.
            </p>
          </div>
        )}

        {answerRequired && (
          <label className="flex items-start gap-3 rounded-xl bg-gray-50 p-3 cursor-pointer">
            <input
              type="checkbox"
              className="mt-1"
              checked={form.allow_autofill}
              onChange={(event) => setForm((current) => ({ ...current, allow_autofill: event.target.checked }))}
            />
            <span>
              <span className="block text-sm font-medium text-gray-900">
                I confirm this answer and authorize automatic use
              </span>
              <span className="block text-xs text-gray-500 mt-0.5">
                Editing the answer later automatically revokes confirmation and disables autofill.
              </span>
            </span>
          </label>
        )}

        <button
          type="submit"
          disabled={createMutation.isPending}
          className="btn-primary flex items-center justify-center gap-2 w-full"
        >
          {createMutation.isPending
            ? <><Loader2 className="w-4 h-4 animate-spin" />Saving</>
            : <><Plus className="w-4 h-4" />Add answer policy</>}
        </button>
      </form>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-900">Saved policies</h3>
          <span className="text-xs text-gray-500">{(policiesQuery.data || []).length} total</span>
        </div>

        {(policiesQuery.data || []).length === 0 ? (
          <div className="text-sm text-gray-500 text-center border border-dashed border-gray-200 rounded-xl py-8">
            No answers are authorized yet. Applications will pause on required custom questions.
          </div>
        ) : (
          <div className="space-y-3">
            {(policiesQuery.data || []).map((policy) => {
              const catalogItem = catalogByKey[policy.canonical_key]
              const canAuthorize = ['answer', 'decline'].includes(policy.mode)
              const authorized = Boolean(policy.allow_autofill && policy.confirmed_at && policy.is_active)
              return (
                <div key={policy.id} className="rounded-xl border border-gray-200 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold text-gray-900">
                          {catalogItem?.label || policy.canonical_key}
                        </p>
                        <span className={`text-[10px] uppercase tracking-wide border rounded-full px-2 py-0.5 ${sensitivityClass(policy.sensitivity)}`}>
                          {policy.sensitivity}
                        </span>
                        {authorized ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-700">
                            <CheckCircle2 className="w-3 h-3" /> Authorized
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-700">
                            <AlertTriangle className="w-3 h-3" /> Review only
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mt-1">
                        {policy.mode.replaceAll('_', ' ')}
                        {policy.answer_value ? ` · ${policy.answer_value}` : ''}
                        {policy.scope !== 'global' ? ` · ${policy.scope}: ${policy.scope_value}` : ' · all applications'}
                      </p>
                    </div>

                    <button
                      type="button"
                      className="text-gray-400 hover:text-red-600 p-1"
                      aria-label="Delete answer policy"
                      onClick={() => deleteMutation.mutate(policy.id)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="flex flex-wrap gap-2 mt-3">
                    {canAuthorize && !authorized && (
                      <button
                        type="button"
                        className="text-xs font-medium px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-700"
                        onClick={() => updateMutation.mutate({
                          id: policy.id,
                          data: { allow_autofill: true, confirmed: true, is_active: true },
                        })}
                      >
                        Confirm and authorize
                      </button>
                    )}
                    {authorized && (
                      <button
                        type="button"
                        className="text-xs font-medium px-3 py-1.5 rounded-lg bg-amber-50 text-amber-700"
                        onClick={() => updateMutation.mutate({
                          id: policy.id,
                          data: { allow_autofill: false },
                        })}
                      >
                        Disable autofill
                      </button>
                    )}
                    <button
                      type="button"
                      className="text-xs font-medium px-3 py-1.5 rounded-lg bg-gray-100 text-gray-700"
                      onClick={() => updateMutation.mutate({
                        id: policy.id,
                        data: { is_active: !policy.is_active },
                      })}
                    >
                      {policy.is_active ? 'Pause policy' : 'Activate policy'}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
