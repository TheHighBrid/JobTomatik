import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Loader2, Plus } from 'lucide-react'

import { createAnswerPolicy, getApiErrorMessage } from '../api/client'

function customPolicyKey(question) {
  const text = String(question || '').trim()
  const slug = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')
    .slice(0, 48)
  let hash = 0
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0
  }
  return `custom.${slug || 'question'}_${Math.abs(hash).toString(36)}`
}

const initialForm = {
  question: '',
  answer_value: '',
  fallback_answers: '',
  allow_autofill: true,
}

export default function CustomQuestionPolicyForm({ onSaved }) {
  const [form, setForm] = useState(initialForm)

  const createMutation = useMutation({
    mutationFn: (payload) => createAnswerPolicy(payload),
    onSuccess: () => {
      toast.success('Custom question saved')
      setForm(initialForm)
      onSaved?.()
    },
    onError: (error) => toast.error(getApiErrorMessage(error, 'Could not save custom question')),
  })

  const submit = (event) => {
    event.preventDefault()
    const question = form.question.trim()
    const answer = form.answer_value.trim()
    if (!question) {
      toast.error('Paste the exact application question')
      return
    }
    if (!answer) {
      toast.error('Add the answer for that exact question')
      return
    }
    const fallbacks = form.fallback_answers
      .split(/[;|\n]+/)
      .map((item) => item.trim())
      .filter(Boolean)
    createMutation.mutate({
      canonical_key: customPolicyKey(question),
      match_phrases: [question],
      mode: 'answer',
      answer_value: answer,
      answer_label: answer,
      fallback_answers: fallbacks,
      scope: 'global',
      scope_value: '',
      allow_autofill: Boolean(form.allow_autofill),
      confirmed: Boolean(form.allow_autofill),
      is_active: true,
    })
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border border-tomato-200 bg-tomato-50/30 p-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Add a custom question</h3>
        <p className="text-xs text-gray-500 mt-1">
          Paste the employer wording exactly. Recheck binds this sentence, not a catalog label.
        </p>
      </div>
      <div>
        <label className="label">Exact application question</label>
        <textarea
          className="input w-full min-h-[88px] resize-y"
          required
          placeholder="Example: Are you located in Canada?"
          value={form.question}
          onChange={(event) => setForm((current) => ({ ...current, question: event.target.value }))}
        />
      </div>
      <div>
        <label className="label">Answer</label>
        <input
          className="input w-full"
          required
          placeholder="Example: Yes"
          value={form.answer_value}
          onChange={(event) => setForm((current) => ({ ...current, answer_value: event.target.value }))}
        />
      </div>
      <div>
        <label className="label">Fallback option labels</label>
        <textarea
          className="input w-full min-h-[64px] resize-y"
          placeholder="One per line. Example: Acknowledged and agreed."
          value={form.fallback_answers}
          onChange={(event) => setForm((current) => ({ ...current, fallback_answers: event.target.value }))}
        />
      </div>
      <label className="flex items-start gap-3 rounded-xl bg-white p-3 cursor-pointer">
        <input
          type="checkbox"
          className="mt-1"
          checked={form.allow_autofill}
          onChange={(event) => setForm((current) => ({ ...current, allow_autofill: event.target.checked }))}
        />
        <span>
          <span className="block text-sm font-medium text-gray-900">I confirm this answer and automatic use</span>
          <span className="block text-xs text-gray-500 mt-0.5">
            Uncheck to save the wording without authorizing autofill.
          </span>
        </span>
      </label>
      <button
        type="submit"
        disabled={createMutation.isPending}
        className="btn-primary w-full flex items-center justify-center gap-2"
      >
        {createMutation.isPending
          ? <><Loader2 className="w-4 h-4 animate-spin" />Saving</>
          : <><Plus className="w-4 h-4" />Save custom question</>}
      </button>
    </form>
  )
}
