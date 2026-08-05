import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/components/LeverPhaseBLaunchPanel.jsx', import.meta.url),
  'utf8',
)

test('Lever launch panel exposes every local Day 16 preparation stage', () => {
  for (const stage of [
    'not_materialized',
    'verified_materials_required',
    'review_required',
    'fresh_preflight_required',
    'active_approval_present',
    'submission_state_present',
  ]) {
    assert.equal(source.includes(stage), true, `missing stage ${stage}`)
  }
  assert.equal(source.includes('preparation_blockers'), true)
  assert.equal(source.includes('preparation_next_action'), true)
  assert.equal(source.includes('cover_letter_review_status'), true)
  assert.equal(source.includes('resume_summary_review_status'), true)
  assert.equal(source.includes('official_posting_context_present'), true)
})

test('preparation actions route to exact owner review and application surfaces', () => {
  assert.equal(
    source.includes('to: `/evidence-materials?application=${applicationId}`'),
    true,
  )
  assert.equal(source.includes('to: `/applications/${applicationId}`'), true)
  assert.equal(source.includes('Review generated bundle'), true)
  assert.equal(source.includes('Open fresh preflight'), true)
  assert.equal(source.includes('Review active approval'), true)
  assert.equal(source.includes('Inspect submission state'), true)
})

test('retained preparation uses official-source bundle endpoint without execution controls', () => {
  assert.equal(
    source.includes('/prepare-materials`'),
    true,
  )
  assert.equal(source.includes('Prepare real material bundle'), true)
  assert.equal(source.includes('Refresh real material bundle'), true)
  assert.equal(source.includes('exact public Lever posting metadata'), true)
  assert.equal(source.includes('/approvals'), false)
  assert.equal(source.includes('/submit'), false)
  assert.equal(source.includes('queueSupervisedSubmission'), false)
  assert.equal(source.includes('createSupervisedSubmissionApproval'), false)
})
