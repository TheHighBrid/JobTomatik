import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(
  new URL('../src/components/CurrentLeverOperatorPanel.jsx', import.meta.url),
  'utf8',
)
const targetForm = readFileSync(
  new URL('../src/components/CurrentLeverTargetForm.jsx', import.meta.url),
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

test('owner can add an exact Lever target in the app without a terminal intake command', () => {
  assert.equal(targetForm.includes("api.post('/supervised-pilot/lever-candidates'"), true)
  assert.equal(targetForm.includes('Verify and add target'), true)
  assert.equal(targetForm.includes('Owner-selected in JobTomatik current Lever operator UI'), true)
  assert.equal(targetForm.includes('does not approve or submit the application'), true)
  assert.equal(targetForm.includes('--owner-email'), false)
  assert.equal(targetForm.includes('proot-distro'), false)
})

test('material decision is exact-application and exact-displayed-bundle bound', () => {
  assert.equal(
    panel.includes('acknowledgment: `APPROVE LEVER MATERIALS ${applicationId}`'),
    true,
  )
  assert.equal(panel.includes('material_ids:'), true)
  assert.equal(panel.includes('material_versions:'), true)
  assert.equal(panel.includes('posting_sha256: postingSha256'), true)
  assert.equal(panel.includes('evidence_digest: coverEvidenceDigest'), true)
  assert.equal(panel.includes('Confirm material approval'), true)
  assert.equal(panel.includes('Approve displayed bundle'), true)
  assert.equal(panel.includes('rejected as stale'), true)
})

test('non-critical warnings remain visible but do not disable owner approval', () => {
  assert.equal(panel.includes('Non-critical review warning:'), true)
  assert.equal(panel.includes('visible non-critical warning'), true)
  assert.equal(panel.includes('criticalErrors.length === 0'), true)
  assert.equal(panel.includes("cover?.warnings?.length || 0"), true)
  assert.equal(panel.includes("resume?.warnings?.length || 0"), true)
})

test('already-approved bundles do not offer duplicate material approval', () => {
  assert.equal(panel.includes('bundleAlreadyApproved'), true)
  assert.equal(panel.includes('This exact material bundle is already approved.'), true)
  assert.equal(panel.includes('Material approval will not be repeated.'), true)
  assert.equal(
    panel.includes("candidate.automation_state === 'needs_review' && !bundleAlreadyApproved"),
    true,
  )
})

test('uncertain live attempts quarantine mutations but preserve read-only evidence inspection', () => {
  assert.equal(panel.includes('Quarantined · no retry'), true)
  assert.equal(panel.includes('uncertain_submission_attempt_count'), true)
  assert.equal(panel.includes('locked against preparation and retry'), true)
  assert.equal(panel.includes('enabled: expanded,'), true)
  assert.equal(panel.includes('enabled: expanded && !quarantined'), false)
  assert.equal(panel.includes('Inspect frozen materials'), true)
  assert.equal(panel.includes('Read-only evidence view.'), true)
  assert.equal(panel.includes('&& !quarantined'), true)
})

test('current Lever operator has no submission-authority endpoint', () => {
  const combined = panel + targetForm
  assert.equal(combined.includes('/approvals'), false)
  assert.equal(combined.includes('/submit'), false)
  assert.equal(combined.includes('queueSupervisedSubmission'), false)
  assert.equal(combined.includes('createSupervisedSubmissionApproval'), false)
  assert.equal(
    panel.includes('It does not issue a submission approval, queue work, enable live flags, or click submit.'),
    true,
  )
})
