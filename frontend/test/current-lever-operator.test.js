import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(
  new URL('../src/components/CurrentLeverOperatorPanel.jsx', import.meta.url),
  'utf8',
)
const app = readFileSync(
  new URL('../src/App.jsx', import.meta.url),
  'utf8',
)
const mobileNav = readFileSync(
  new URL('../src/components/MobileNav.jsx', import.meta.url),
  'utf8',
)
const layout = readFileSync(
  new URL('../src/components/Layout.jsx', import.meta.url),
  'utf8',
)

test('current Lever operator is a first-class app route on desktop and mobile', () => {
  assert.equal(app.includes('path="current-lever"'), true)
  assert.equal(mobileNav.includes("to: '/current-lever'"), true)
  assert.equal(layout.includes("to: '/current-lever'"), true)
})

test('operator handles current roster, materials, preparation, and review without CLI fields', () => {
  assert.equal(panel.includes("api.get('/supervised-pilot/current-lever')"), true)
  assert.equal(panel.includes('/prepare-materials`'), true)
  assert.equal(panel.includes('/materials`'), true)
  assert.equal(panel.includes('/review-materials`'), true)
  assert.equal(panel.includes('--owner-email'), false)
  assert.equal(panel.includes('--application-id'), false)
})

test('material approval remains exact-application bound and deliberate', () => {
  assert.equal(
    panel.includes('acknowledgment: `APPROVE LEVER MATERIALS ${applicationId}`'),
    true,
  )
  assert.equal(panel.includes('Confirm material approval'), true)
  assert.equal(panel.includes('Approve verified bundle'), true)
})

test('uncertain live attempts are quarantined and cannot be prepared or reviewed', () => {
  assert.equal(panel.includes('Quarantined · no retry'), true)
  assert.equal(panel.includes('uncertain_submission_attempt_count'), true)
  assert.equal(panel.includes('locked against preparation and retry'), true)
})

test('current Lever operator has no submission-authority endpoint', () => {
  assert.equal(panel.includes('/approvals'), false)
  assert.equal(panel.includes('/submit'), false)
  assert.equal(panel.includes('queueSupervisedSubmission'), false)
  assert.equal(panel.includes('createSupervisedSubmissionApproval'), false)
  assert.equal(
    panel.includes('It does not issue a submission approval, queue work, enable live flags, or click submit.'),
    true,
  )
})
