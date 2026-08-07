import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/FollowUpReview.jsx', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../src/api/client.js', import.meta.url),
  'utf8',
)
const settingsSource = readFileSync(
  new URL('../src/pages/Settings.jsx', import.meta.url),
  'utf8',
)
const appSource = readFileSync(
  new URL('../src/App.jsx', import.meta.url),
  'utf8',
)
const layoutSource = readFileSync(
  new URL('../src/components/Layout.jsx', import.meta.url),
  'utf8',
)

test('follow-up workspace keeps application approval separate from outreach consent', () => {
  assert.equal(
    pageSource.includes('Application submission approval does not authorize recruiter outreach.'),
    true,
  )
  assert.equal(pageSource.includes('Approve exact follow-up'), true)
  assert.equal(pageSource.includes('expected_acknowledgment'), true)
  assert.equal(pageSource.includes('ALLOW_REAL_FOLLOWUP_SEND remains off.'), true)
  assert.equal(pageSource.includes('Mock mode cannot send recruiter email.'), true)
})

test('follow-up workspace exposes exact-payload edit approval revoke and send APIs', () => {
  assert.equal(apiSource.includes('updateFollowup'), true)
  assert.equal(apiSource.includes('getFollowupPreflight'), true)
  assert.equal(apiSource.includes('approveFollowup'), true)
  assert.equal(apiSource.includes('revokeFollowup'), true)
  assert.equal(apiSource.includes('sendFollowup'), true)
  assert.equal(pageSource.includes('Save exact draft'), true)
  assert.equal(pageSource.includes('Queue approved delivery'), true)
})

test('follow-up workspace is routed and available from primary navigation', () => {
  assert.equal(appSource.includes('FollowUpReview'), true)
  assert.equal(appSource.includes('path="followup-review"'), true)
  assert.equal(layoutSource.includes("to: '/followup-review'"), true)
  assert.equal(layoutSource.includes("label: 'Follow-up Review'"), true)
})

test('settings describe automatic follow-up as draft preparation rather than sending', () => {
  assert.equal(settingsSource.includes('Auto-Prepare Follow-up Drafts'), true)
  assert.equal(settingsSource.includes('nothing is sent automatically'), true)
  assert.equal(settingsSource.includes('Auto-Schedule Follow-ups'), false)
  assert.equal(
    settingsSource.includes('Send a follow-up email N days after a confirmed application'),
    false,
  )
})
