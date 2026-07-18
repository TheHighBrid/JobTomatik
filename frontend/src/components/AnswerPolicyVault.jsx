import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Loader2,
  Plus, Save, Search, ShieldCheck, Trash2,
} from 'lucide-react'

import {
  bulkUpsertAnswerPolicies,
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
  fallback_answers: '',
  scope: 'global',
  scope_value: '',
  allow_autofill: false,
}

function sensitivityClass(value) {
  if (value === 'legal') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (value === 'sensitive') return 'bg-purple-50 text-purple-700 border-purple-200'
  return 'bg-gray-50 text-gray-600 border-gray-200'
}

function splitAnswers(value) {
  return String(value || '')
    .split(/[;|\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function addAnswer(value, answer) {
  const current = splitAnswers(value)
  if (!current.some((item) => item.toLowerCase() === answer.toLowerCase())) current.push(answer)
  return current.join('\n')
}

function emptySetupRow(item) {
  return {
    include: false,
    mode: item.default_mode || 'answer',
    answer_value: '',
    fallback_answers: '',
  }
}

export default function AnswerPolicyVault() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialForm)
  const [setupOpen, setSetupOpen] = useState(false)
  const [setupSearch, setSetupSearch] = useState('')
  const [setupRows, setSetupRows] = useState({})
  const [setupConfirmed, setSetupConfirmed] = useState(false)

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

  const filteredGroups = useMemo(() => {
    const query = setupSearch.trim().toLowerCase()
    const filtered = (catalogQuery.data || []).filter((item) => !query || [
      item.label, item.description, item.category, item.setup_group,
    ].some((value) => String(value || '').toLowerCase().includes(query)))
    return filtered.reduce((groups, item) => {
      const name = item.setup_group || 'Other'
      groups[name] = [...(groups[name] || []), item]
      return groups
    }, {})
  }, [catalogQuery.data, setupSearch])

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

  const bulkMutation = useMutation({
    mutationFn: (payload) => bulkUpsertAnswerPolicies(payload),
    onSuccess: (response) => {
      const { created, updated } = response.data
      toast.success(`Policy pack saved: ${created} added, ${updated} updated`)
      setSetupOpen(false)
      setSetupConfirmed(false)
      invalidate()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not save policy pack')),
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
      fallback_answers: answerRequired ? splitAnswers(form.fallback_answers) : [],
      scope: form.scope,
      scope_value: scopeValueRequired ? form.scope_value.trim() : '',
      allow_autofill: allowAutofill,
      confirmed: allowAutofill,
      is_active: true,
    })
  }

  const openBulkSetup = () => {
    const globalPolicies = Object.fromEntries(
      (policiesQuery.data || [])
        .filter((policy) => policy.scope === 'global')
        .map((policy) => [policy.canonical_key, policy])
    )
    const rows = {}
    for (const item of catalogQuery.data || []) {
      const saved = globalPolicies[item.canonical_key]
      rows[item.canonical_key] = saved ? {
        include: true,
        mode: saved.mode,
        answer_value: saved.answer_value || saved.answer_label || '',
        fallback_answers: (saved.fallback_answers || []).join('\n'),
      } : emptySetupRow(item)
    }
    setSetupRows(rows)
    setSetupConfirmed(false)
    setSetupOpen(true)
  }

  const updateSetupRow = (key, updates) => {
    setSetupRows((current) => ({
      ...current,
      [key]: { ...(current[key] || emptySetupRow(catalogByKey[key] || {})), ...updates },
    }))
  }

  const saveBulkSetup = () => {
    const included = (catalogQuery.data || []).filter((item) => (
      setupRows[item.canonical_key]?.include
    ))
    const invalid = included.find((item) => {
      const row = setupRows[item.canonical_key] || emptySetupRow(item)
      return ['answer', 'decline'].includes(row.mode) && !row.answer_value.trim()
    })
    if (!included.length) return toast.error('Choose at least one answer policy')
    if (invalid) return toast.error(`Add an answer for ${invalid.label}`)
    if (!setupConfirmed) return toast.error('Confirm the completed policy pack before saving')

    const items = included.map((item) => {
      const row = setupRows[item.canonical_key] || emptySetupRow(item)
      const needsAnswer = ['answer', 'decline'].includes(row.mode)
      return {
        canonical_key: item.canonical_key,
        mode: row.mode,
        answer_value: needsAnswer ? row.answer_value.trim() : null,
        answer_label: needsAnswer ? row.answer_value.trim() : null,
        fallback_answers: needsAnswer ? splitAnswers(row.fallback_answers) : [],
        scope: 'global',
        scope_value: '',
        allow_autofill: needsAnswer,
        confirmed: needsAnswer,
        is_active: true,
      }
    })
    bulkMutation.mutate({ items })
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
              Primary answers and fallback option labels are encrypted. JobTomatik tries them in your order
              and never picks an unrelated option. Unknown required questions still stop for review.
            </p>
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={setupOpen ? () => setSetupOpen(false) : openBulkSetup}
        className="w-full rounded-xl border border-tomato-200 bg-tomato-50 p-4 text-left flex items-center justify-between"
      >
        <span>
          <span className="block text-sm font-semibold text-tomato-900">Guided policy setup</span>
          <span className="block text-xs text-tomato-700 mt-1">
            Complete many common application answers, fallbacks, and review rules in one save.
          </span>
        </span>
        {setupOpen ? <ChevronUp className="w-5 h-5 text-tomato-700" /> : <ChevronDown className="w-5 h-5 text-tomato-700" />}
      </button>

      {setupOpen && (
        <div className="rounded-xl border border-gray-200 p-4 space-y-5">
          <div className="relative">
            <Search className="absolute left-3 top-3 w-4 h-4 text-gray-400" />
            <input
              className="input w-full pl-9"
              placeholder="Search eligibility, demographics, consent, salary..."
              value={setupSearch}
              onChange={(event) => setSetupSearch(event.target.value)}
            />
          </div>

          {Object.entries(filteredGroups).map(([group, items]) => (
            <section key={group} className="space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wide text-gray-500">{group}</h3>
              {items.map((item) => {
                const row = setupRows[item.canonical_key] || emptySetupRow(item)
                const needsAnswer = ['answer', 'decline'].includes(row.mode)
                return (
                  <div key={item.canonical_key} className={`rounded-xl border p-3 ${row.include ? 'border-tomato-200 bg-tomato-50/30' : 'border-gray-200'}`}>
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={row.include}
                        onChange={(event) => updateSetupRow(item.canonical_key, { include: event.target.checked })}
                      />
                      <span className="flex-1 min-w-0">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-gray-900">{item.label}</span>
                          <span className={`text-[10px] uppercase tracking-wide border rounded-full px-2 py-0.5 ${sensitivityClass(item.sensitivity)}`}>
                            {item.sensitivity}
                          </span>
                        </span>
                        <span className="block text-xs text-gray-500 mt-1">{item.description}</span>
                      </span>
                    </label>

                    {row.include && (
                      <div className="mt-3 ml-7 space-y-3">
                        <select
                          className="input w-full"
                          value={row.mode}
                          onChange={(event) => updateSetupRow(item.canonical_key, { mode: event.target.value })}
                        >
                          <option value="answer">Use my answer</option>
                          <option value="decline">Use my decline/prefer-not answer</option>
                          <option value="ask_each_time">Ask every time</option>
                          <option value="skip">Never answer automatically</option>
                        </select>

                        {needsAnswer && (
                          <>
                            <input
                              className="input w-full"
                              placeholder="Primary answer or exact option label"
                              value={row.answer_value}
                              onChange={(event) => updateSetupRow(item.canonical_key, { answer_value: event.target.value })}
                            />
                            {!!item.suggested_answers?.length && (
                              <div className="flex flex-wrap gap-1.5">
                                {item.suggested_answers.map((answer) => (
                                  <button
                                    type="button"
                                    key={answer}
                                    className="text-[11px] px-2 py-1 rounded-full bg-white border border-gray-200 text-gray-700"
                                    onClick={() => updateSetupRow(item.canonical_key, { answer_value: answer })}
                                  >
                                    {answer}
                                  </button>
                                ))}
                              </div>
                            )}
                            <textarea
                              className="input w-full min-h-[72px] resize-y"
                              placeholder="Fallback option labels, one per line. Example: Male, Man, M"
                              value={row.fallback_answers}
                              onChange={(event) => updateSetupRow(item.canonical_key, { fallback_answers: event.target.value })}
                            />
                            {!!item.fallback_suggestions?.length && (
                              <div>
                                <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">Common labels to add if accurate</p>
                                <div className="flex flex-wrap gap-1.5">
                                  {item.fallback_suggestions.map((answer) => (
                                    <button
                                      type="button"
                                      key={answer}
                                      className="text-[11px] px-2 py-1 rounded-full bg-gray-100 text-gray-600"
                                      onClick={() => updateSetupRow(item.canonical_key, {
                                        fallback_answers: addAnswer(row.fallback_answers, answer),
                                      })}
                                    >
                                      + {answer}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </section>
          ))}

          <label className="flex items-start gap-3 rounded-xl bg-gray-50 p-3 cursor-pointer">
            <input
              type="checkbox"
              className="mt-1"
              checked={setupConfirmed}
              onChange={(event) => setSetupConfirmed(event.target.checked)}
            />
            <span>
              <span className="block text-sm font-medium text-gray-900">I reviewed every included answer and fallback</span>
              <span className="block text-xs text-gray-500 mt-0.5">
                Completed answer and decline policies will be confirmed and authorized together.
              </span>
            </span>
          </label>

          <button
            type="button"
            disabled={bulkMutation.isPending}
            onClick={saveBulkSetup}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {bulkMutation.isPending
              ? <><Loader2 className="w-4 h-4 animate-spin" />Saving policy pack</>
              : <><Save className="w-4 h-4" />Save all included policies</>}
          </button>
        </div>
      )}

      <form onSubmit={submit} className="space-y-4 rounded-xl border border-gray-200 p-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Add one policy</h3>
          <p className="text-xs text-gray-500 mt-1">Use this for one-off platform or company overrides.</p>
        </div>
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
                allow_autofill: ['answer', 'decline'].includes(event.target.value) ? current.allow_autofill : false,
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
          <>
            <div>
              <label className="label">Primary answer</label>
              <input
                className="input w-full"
                required
                placeholder="Example: Male, Yes, No, 90,000 CAD"
                value={form.answer_value}
                onChange={(event) => setForm((current) => ({ ...current, answer_value: event.target.value }))}
              />
            </div>
            <div>
              <label className="label">Fallback option labels</label>
              <textarea
                className="input w-full min-h-[72px] resize-y"
                placeholder="One per line, in order: Man, M, Prefer not to answer"
                value={form.fallback_answers}
                onChange={(event) => setForm((current) => ({ ...current, fallback_answers: event.target.value }))}
              />
              <p className="text-[11px] text-gray-500 mt-1">
                JobTomatik tries the primary answer first, then each approved fallback. It stops if none match unambiguously.
              </p>
            </div>
          </>
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
              <span className="block text-sm font-medium text-gray-900">I confirm this answer, its fallbacks, and automatic use</span>
              <span className="block text-xs text-gray-500 mt-0.5">
                Editing the primary answer or any fallback later revokes confirmation.
              </span>
            </span>
          </label>
        )}

        <button type="submit" disabled={createMutation.isPending} className="btn-primary flex items-center justify-center gap-2 w-full">
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
                        <p className="text-sm font-semibold text-gray-900">{catalogItem?.label || policy.canonical_key}</p>
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
                      {!!policy.fallback_answers?.length && (
                        <p className="text-[11px] text-gray-500 mt-1">
                          Fallbacks: {policy.fallback_answers.join(' → ')}
                        </p>
                      )}
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
                        onClick={() => updateMutation.mutate({ id: policy.id, data: { allow_autofill: false } })}
                      >
                        Disable autofill
                      </button>
                    )}
                    <button
                      type="button"
                      className="text-xs font-medium px-3 py-1.5 rounded-lg bg-gray-100 text-gray-700"
                      onClick={() => updateMutation.mutate({ id: policy.id, data: { is_active: !policy.is_active } })}
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
