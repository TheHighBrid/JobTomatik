import assert from 'node:assert/strict'
import test from 'node:test'
import { customPolicyKey, customQuestionPayload, questionFromDescriptor } from '../src/customQuestionPolicies.js'

const form = (changes = {}) => ({
  question: 'What is your preferred work arrangement?', answer_value: 'Hybrid',
  variations: '', fallback_answers: '', scope: 'global', scope_value: '',
  allow_autofill: false, ...changes,
})

test('custom questions retain verbatim wording, approved variations and scoped answers', () => {
  const payload = customQuestionPayload(form({
    variations: ' Which work arrangement do you prefer? ',
    fallback_answers: 'Hybrid\nRemote; flexible\nHybrid', scope: 'company', scope_value: ' Example Ltd ', allow_autofill: true,
  }))
  assert.deepEqual(payload.match_phrases, ['What is your preferred work arrangement?', 'Which work arrangement do you prefer?'])
  assert.deepEqual(payload.fallback_answers, ['Hybrid', 'Remote; flexible'])
  assert.equal(payload.answer_value, 'Hybrid')
  assert.equal(payload.scope_value, 'Example Ltd')
  assert.equal(payload.confirmed, true)
  assert.equal(payload.source_metadata.question_match_mode, 'exact')
})

test('draft answers never authorize automatic reuse', () => {
  const payload = customQuestionPayload(form())
  assert.equal(payload.allow_autofill, false)
  assert.equal(payload.confirmed, false)
})

test('a multiline employer prompt remains one complete saved question', () => {
  const question = 'Please describe your experience\nwith bilingual customer support.'
  assert.deepEqual(customQuestionPayload(form({ question })).match_phrases, [question])
})

test('editing retains the existing key and custom metadata', () => {
  const payload = customQuestionPayload(form(), { id: 7, canonical_key: 'custom.original', source_metadata: { imported: true } })
  assert.equal('canonical_key' in payload, false)
  assert.equal(payload.source_metadata.imported, true)
})

test('question identities normalize formatting but preserve meaningful differences and Unicode', () => {
  assert.equal(customPolicyKey('  Quel est votre prénom ?'), customPolicyKey('QUEL EST VOTRE PRÉNOM!'))
  for (const [first, second] of [
    ['What is your gender identity?', 'What is your sexual orientation?'],
    ['What is your salary expectation?', 'What is your total compensation expectation?'],
    ['你是否愿意出差？', '你是否愿意搬家？'],
    ['a'.repeat(100) + 'one', 'a'.repeat(100) + 'two'],
  ]) assert.notEqual(customPolicyKey(first), customPolicyKey(second))
})

test('empty input and missing company are rejected; long written answers fit the API', () => {
  for (const changes of [{ question: '  ' }, { question: '???' }, { answer_value: ' ' }, { scope: 'company', scope_value: '' }]) {
    assert.throws(() => customQuestionPayload(form(changes)))
  }
  const payload = customQuestionPayload(form({ answer_value: 'a'.repeat(4000) }))
  assert.equal(payload.answer_value.length, 4000)
  assert.equal(payload.answer_label, null)
})

test('retained Lever prompt is presented without card ID or option noise', () => {
  assert.equal(questionFromDescriptor('cards[abc][field0] | Yes | Are you available on weekends?'), 'Are you available on weekends?')
  assert.equal(questionFromDescriptor('Tell us about your experience.'), 'Tell us about your experience.')
})
