import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/ShadowCampaignCenter.jsx', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../src/api/shadowCampaigns.js', import.meta.url),
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

test('Shadow Campaign Center exposes exact start and stop controls', () => {
  assert.equal(pageSource.includes('Exact start acknowledgment'), true)
  assert.equal(pageSource.includes('expected_start_acknowledgment'), true)
  assert.equal(pageSource.includes('Exact stop acknowledgment'), true)
  assert.equal(pageSource.includes('expected_stop_acknowledgment'), true)
  assert.equal(pageSource.includes('Start full-stack shadow campaign'), true)
  assert.equal(pageSource.includes('Stop campaign'), true)
})

test('Shadow Campaign Center states the no-submit and unreviewed evidence boundary', () => {
  assert.equal(pageSource.includes('No-submit evidence collection'), true)
  assert.equal(pageSource.includes('never enables real submission or recruiter outreach'), true)
  assert.equal(pageSource.includes('unreviewed evidence record'), true)
  assert.equal(pageSource.includes('Independent verification remains a separate action'), true)
})

test('Shadow Campaign Center surfaces qualification and settling evidence', () => {
  assert.equal(pageSource.includes('What earns qualification'), true)
  assert.equal(pageSource.includes('Settling is intentional.'), true)
  assert.equal(pageSource.includes('no_false_submitted_status'), false)
  assert.equal(pageSource.includes('session.final_report?.quality'), true)
  assert.equal(pageSource.includes('report_sha256'), true)
  assert.equal(pageSource.includes('qualification_eligible'), true)
})

test('Shadow campaign client uses account-scoped API routes and allows bounded qualification time', () => {
  assert.equal(apiSource.includes("api.get('/shadow-runs/preflight'"), true)
  assert.equal(apiSource.includes("api.get('/shadow-runs'"), true)
  assert.equal(apiSource.includes("api.post('/shadow-runs', data, { timeout: 10 * 60 * 1000 })"), true)
  assert.equal(apiSource.includes('/shadow-runs/${sessionId}/stop'), true)
  assert.equal(apiSource.includes('/shadow-runs/${sessionId}/record-evidence'), true)
})

test('Shadow Campaign Center is routed and present in primary navigation', () => {
  assert.equal(appSource.includes('ShadowCampaignCenter'), true)
  assert.equal(appSource.includes('path="shadow-campaigns"'), true)
  assert.equal(layoutSource.includes("to: '/shadow-campaigns'"), true)
  assert.equal(layoutSource.includes("label: 'Shadow Campaigns'"), true)
})
