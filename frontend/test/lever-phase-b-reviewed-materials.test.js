import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/pages/EvidenceMaterials.jsx', import.meta.url),
  'utf8',
)

test('retained Lever applications use official-context preparation instead of generic generation', () => {
  assert.equal(source.includes('isRetainedLever'), true)
  assert.equal(source.includes('Prepare official-source bundle'), true)
  assert.equal(source.includes('/prepare-materials`'), true)
  assert.equal(
    source.includes('Generic material generation is disabled for this candidate'),
    true,
  )
})

test('owner must review both latest source-valid materials before local readiness', () => {
  assert.equal(source.includes('retainedReviewEligible'), true)
  assert.equal(source.includes('retainedBundle.length === 2'), true)
  assert.equal(source.includes('snapshot.review_eligible === true'), true)
  assert.equal(source.includes('Approve reviewed bundle'), true)
  assert.equal(source.includes('Reject bundle'), true)
  assert.equal(source.includes('/review-materials`'), true)
  assert.equal(source.includes('Claim audit'), true)
})

test('material decision copy preserves the no-approval and no-submit boundary', () => {
  assert.equal(
    source.includes('does not approve, queue, or submit an application'),
    true,
  )
  assert.equal(source.includes('createSupervisedSubmissionApproval'), false)
  assert.equal(source.includes('queueSupervisedSubmission'), false)
  assert.equal(source.includes('/approvals'), false)
  assert.equal(source.includes('/submit'), false)
})
