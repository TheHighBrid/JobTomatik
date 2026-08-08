import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/PostApplicationCenter.jsx', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../src/api/postApplication.js', import.meta.url),
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

test('post-application center states the inbound and outbound permission boundaries', () => {
  assert.equal(pageSource.includes('Classification is not permission.'), true)
  assert.equal(pageSource.includes('never changes application status automatically'), true)
  assert.equal(pageSource.includes('independent exact-payload approval'), true)
  assert.equal(pageSource.includes('outbound kill switch'), true)
})

test('post-application center exposes employer inbox interview prep and outcome flows', () => {
  for (const term of [
    'Employer inbox',
    'Classify and record',
    'Confirm ',
    'Interview schedule',
    'Source-backed interview prep',
    'Offer comparison',
    'Record application outcome',
    'Source reference',
  ]) {
    assert.equal(pageSource.includes(term), true, `missing Phase 9 UI contract: ${term}`)
  }
})

test('post-application API keeps status confirmation separate from message ingestion', () => {
  assert.equal(apiSource.includes("api.post(`/post-application/applications/${applicationId}/messages`, data)"), true)
  assert.equal(apiSource.includes('/apply-status`'), true)
  assert.equal(apiSource.includes('/interview`'), true)
  assert.equal(apiSource.includes('/interview-prep`'), true)
  assert.equal(apiSource.includes('/outcome`'), true)
  assert.equal(apiSource.includes("api.get('/post-application/offers')"), true)
})

test('post-application center is routed and present in primary navigation', () => {
  assert.equal(appSource.includes('PostApplicationCenter'), true)
  assert.equal(appSource.includes('path="post-application"'), true)
  assert.equal(layoutSource.includes("to: '/post-application'"), true)
  assert.equal(layoutSource.includes("label: 'Post-Application Center'"), true)
})
