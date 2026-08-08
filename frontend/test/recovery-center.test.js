import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/RecoveryCenter.jsx', import.meta.url),
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

test('Recovery Center exposes retained checkpoint and exact manual actions', () => {
  assert.equal(pageSource.includes('Retained checkpoint'), true)
  assert.equal(pageSource.includes('expected_requeue_acknowledgment'), true)
  assert.equal(pageSource.includes('expected_resolve_acknowledgment'), true)
  assert.equal(pageSource.includes('Requeue bounded task'), true)
  assert.equal(pageSource.includes('Resolve without retry'), true)
})

test('Recovery Center keeps recovery separate from consequential permission', () => {
  assert.equal(pageSource.includes('Recovery is not submission permission.'), true)
  assert.equal(pageSource.includes('cannot submit an application'), true)
  assert.equal(pageSource.includes('send recruiter outreach'), true)
  assert.equal(pageSource.includes('promote adapter maturity'), true)
  assert.equal(pageSource.includes('enable automatic retry'), true)
})

test('Recovery Center uses account-scoped dead-letter APIs', () => {
  assert.equal(pageSource.includes("api.get('/recovery/dead-letters'"), true)
  assert.equal(pageSource.includes('/recovery/dead-letters/${item.task_id}/requeue'), true)
  assert.equal(pageSource.includes('/recovery/dead-letters/${item.task_id}/resolve'), true)
})

test('Recovery Center is routed and present in primary navigation', () => {
  assert.equal(appSource.includes('RecoveryCenter'), true)
  assert.equal(appSource.includes('path="recovery"'), true)
  assert.equal(layoutSource.includes("to: '/recovery'"), true)
  assert.equal(layoutSource.includes("label: 'Recovery Center'"), true)
})
