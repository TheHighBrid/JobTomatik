import { useId, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Loader2, Save } from 'lucide-react'
import { createAnswerPolicy, updateAnswerPolicy, getApiErrorMessage } from '../api/client'
import { customQuestionPayload } from '../customQuestionPolicies'

export default function CustomQuestionPolicyForm({
  onSaved, onCancel, policy, initialQuestion = '', initialCompany = '',
  initialApplicationUrl = '', availableOptions = [], recheck = false,
}) {
  const id = useId()
  const initialForm = () => ({
    question: policy?.match_phrases?.[0] || initialQuestion,
    variations: (policy?.match_phrases || []).slice(1).join('\n'),
    answer_value: policy?.answer_value || policy?.answer_label || '',
    fallback_answers: (policy?.fallback_answers || []).join('\n'),
    scope: policy?.scope || (initialApplicationUrl ? 'application' : (initialCompany ? 'company' : 'global')),
    scope_value: policy?.scope_value || initialApplicationUrl || initialCompany,
    allow_autofill: false,
  })
  const [form, setForm] = useState(initialForm)
  const [savedPolicy, setSavedPolicy] = useState(policy || null)
  const [saveError, setSaveError] = useState('')
  const [recheckError, setRecheckError] = useState('')
  const change = (field, value) => {
    setForm((current) => ({ ...current, [field]: value, allow_autofill: false }))
    setSaveError('')
  }
  const changeScope = (scope) => {
    const scopeValue = scope === 'application'
      ? initialApplicationUrl
      : scope === 'company'
        ? initialCompany
        : scope === 'global'
          ? ''
          : form.scope === scope ? form.scope_value : ''
    setForm((current) => ({ ...current, scope, scope_value: scopeValue, allow_autofill: false }))
    setSaveError('')
  }
  const saveMutation = useMutation({
    mutationFn: async (payload) => {
      const response = savedPolicy
        ? await updateAnswerPolicy(savedPolicy.id, payload)
        : await createAnswerPolicy(payload)
      setSavedPolicy(response.data)
      return response
    },
    onSuccess: async (response) => {
      setSaveError('')
      setRecheckError('')
      try {
        await onSaved?.(response.data)
        toast.success(recheck ? 'Answer saved and questions rechecked' : 'Custom question saved')
        if (!policy && !recheck) {
          setForm(initialForm())
          setSavedPolicy(null)
        }
      } catch (error) {
        setRecheckError(getApiErrorMessage(error, 'Recheck could not finish. Use Recheck approved answers to retry.'))
        toast.error('Answer saved, but recheck could not finish')
      }
    },
    onError: (error) => setSaveError(getApiErrorMessage(error, 'Could not save custom question')),
  })
  const submit = (event) => {
    event.preventDefault()
    try {
      saveMutation.mutate(customQuestionPayload(form, savedPolicy))
    } catch (error) {
      setSaveError(error.message)
    }
  }
  const scopeLabel = form.scope === 'application'
    ? 'Exact application URL'
    : form.scope === 'company'
      ? 'Company name'
      : 'Platform domain'
  return (
    <form onSubmit={submit} aria-label={policy ? 'Edit custom question' : 'Add a custom question'} className="space-y-4 rounded-xl border border-tomato-200 bg-tomato-50/30 p-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">{policy ? 'Edit custom question' : 'Add a custom question'}</h3>
        <p className="text-xs text-gray-500 mt-1">Save your answer to this wording. Add other wording only when it should use the same answer.</p>
      </div>
      <fieldset disabled={saveMutation.isPending} className="space-y-4">
        <div>
          <label htmlFor={`${id}-question`} className="label">Exact application question</label>
          <textarea id={`${id}-question`} className="input w-full min-h-[88px] resize-y" required value={form.question} onChange={(event) => change('question', event.target.value)} />
        </div>
        <div>
          <label htmlFor={`${id}-variations`} className="label">Other wording for this same question (optional)</label>
          <textarea id={`${id}-variations`} className="input w-full min-h-[64px] resize-y" placeholder="One complete question per line" value={form.variations} onChange={(event) => change('variations', event.target.value)} />
        </div>
        {!!availableOptions.length && (
          <div className="text-xs text-gray-700">
            <p className="font-semibold">Employer choices</p>
            <div className="mt-1 flex flex-wrap gap-2">
              {availableOptions.filter((option) => !option.disabled).map((option, index) => (
                <button key={index} type="button" className="btn-secondary text-xs" onClick={() => change('answer_value', option.value || option.label)}>{option.label || option.value}</button>
              ))}
            </div>
          </div>
        )}
        <div>
          <label htmlFor={`${id}-answer`} className="label">Your answer</label>
          <textarea id={`${id}-answer`} className="input w-full min-h-[72px] resize-y" required maxLength={4000} value={form.answer_value} onChange={(event) => change('answer_value', event.target.value)} />
        </div>
        <div>
          <label htmlFor={`${id}-fallbacks`} className="label">Fallback option labels (optional)</label>
          <textarea id={`${id}-fallbacks`} className="input w-full min-h-[64px] resize-y" placeholder="One approved fallback per line, in order" value={form.fallback_answers} onChange={(event) => change('fallback_answers', event.target.value)} />
        </div>
        <fieldset className="space-y-2">
          <legend className="label">Reuse this answer for</legend>
          <div className="flex flex-wrap gap-3 text-sm text-gray-900">
            {[
              ['application', 'This position only'],
              ['company', 'One company'],
              ['platform', 'One platform/domain'],
              ['global', 'All applications'],
            ].map(([value, label]) => (
              <label key={value} className="flex items-center gap-2">
                <input type="radio" name={`${id}-scope`} value={value} checked={form.scope === value} onChange={() => changeScope(value)} />{label}
              </label>
            ))}
          </div>
          {form.scope === 'application' && (
            <p className="text-xs text-gray-600">Safest for pay, availability, relocation, schedule, and other answers that can change by role. This answer outranks broader company, platform, and global policies only for this exact application.</p>
          )}
          {form.scope !== 'global' && (
            <label className="block label">{scopeLabel}
              <input className="input w-full mt-1" required maxLength={255} value={form.scope_value} onChange={(event) => change('scope_value', event.target.value)} />
            </label>
          )}
        </fieldset>
        <label className="flex items-start gap-3 rounded-xl bg-white p-3 cursor-pointer">
          <input type="checkbox" className="mt-1" checked={form.allow_autofill} onChange={(event) => setForm((current) => ({ ...current, allow_autofill: event.target.checked }))} />
          <span className="text-sm font-medium text-gray-900">I confirm this answer, its wording variations, and automatic reuse</span>
        </label>
        {!form.allow_autofill && <p className="text-xs text-gray-500">Saved answers are used automatically after you confirm reuse.</p>}
        {saveError && <p role="alert" className="text-sm text-red-700">{saveError}</p>}
        {recheckError && <p role="alert" className="text-sm text-amber-700">Answer saved. {recheckError}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="submit" className="btn-primary flex items-center justify-center gap-2">
            {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            {recheck ? 'Save answer and recheck' : 'Save custom question'}
          </button>
          {onCancel && <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>}
        </div>
      </fieldset>
    </form>
  )
}
