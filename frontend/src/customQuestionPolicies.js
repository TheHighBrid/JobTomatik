export function normalizeCustomQuestion(question) {
  return String(question || '').normalize('NFKC').toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}

// Include the full normalized question in the hash, beyond the readable slug.
export function customPolicyKey(question) {
  const text = normalizeCustomQuestion(question)
  const slug = text.replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 48)
  let hash = 0
  for (let i = 0; i < text.length; i += 1) hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0
  return `custom.${slug || 'question'}_${Math.abs(hash).toString(36)}`
}

function lines(value) {
  return [...new Set(String(value || '').split(/\r?\n/).map((item) => item.trim()).filter(Boolean))]
}

export function customQuestionPayload(form, policy) {
  const question = form.question.trim()
  const answer = form.answer_value.trim()
  if (!normalizeCustomQuestion(question)) throw new Error('Enter the application question')
  if (!answer) throw new Error('Enter your answer')
  if (form.scope !== 'global' && !form.scope_value.trim()) throw new Error('Enter the company name or platform domain')
  const phrases = [...new Set([question, ...lines(form.variations)])]
  const fallbacks = lines(form.fallback_answers)
  if (phrases.length > 25) throw new Error('Use up to 24 wording variations')
  if (fallbacks.length > 20) throw new Error('Use up to 20 fallback answers')
  return {
    ...(!policy ? { canonical_key: customPolicyKey(question) } : {}),
    match_phrases: phrases,
    mode: 'answer',
    answer_value: answer,
    answer_label: answer.length <= 1000 ? answer : null,
    fallback_answers: fallbacks,
    scope: form.scope,
    scope_value: form.scope === 'global' ? '' : form.scope_value.trim(),
    allow_autofill: Boolean(form.allow_autofill),
    confirmed: Boolean(form.allow_autofill),
    is_active: true,
    source_metadata: { ...(policy?.source_metadata || {}), question_match_mode: 'exact' },
  }
}

export function questionFromDescriptor(descriptor) {
  const text = String(descriptor || '').trim()
  if (/^cards\[.*?\]\[field\d+\]\s*\|/.test(text)) return text.split(' | ').at(-1).trim()
  return text
}
