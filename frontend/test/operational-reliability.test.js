import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/AdapterHealth.jsx', import.meta.url),
  'utf8',
)
const operationsTaskSource = readFileSync(
  new URL('../../backend/app/tasks/operations.py', import.meta.url),
  'utf8',
)
const discoveryTaskSource = readFileSync(
  new URL('../../backend/app/tasks/scraping.py', import.meta.url),
  'utf8',
)

test('reliability console exposes source, adapter, incident, and recovery evidence', () => {
  for (const term of [
    'Operational Reliability',
    'Active Incidents',
    'Discovery Source Health',
    'Adapter Performance',
    'Open recovery view',
    'Source failures',
  ]) {
    assert.equal(pageSource.includes(term), true, `missing reliability surface: ${term}`)
  }
})

test('reliability console uses dedicated read and notification-sync operations', () => {
  assert.equal(pageSource.includes("api.get('/adapter-health/observability'"), true)
  assert.equal(pageSource.includes("api.post('/adapter-health/observability/notifications/refresh'"), true)
  assert.equal(pageSource.includes('Sync alerts'), true)
})

test('reliability console states its non-consequential safety boundary', () => {
  assert.equal(pageSource.includes('Evidence-only control surface'), true)
  assert.equal(pageSource.includes('cannot enable live submission'), true)
  assert.equal(pageSource.includes('promote adapter maturity'), true)
  assert.equal(pageSource.includes('retry an application'), true)
  assert.equal(pageSource.includes('send recruiter outreach'), true)
})

test('scheduled operations refresh incidents without changing its runtime task identity', () => {
  assert.equal(operationsTaskSource.includes('app.tasks.operations.refresh_adapter_health_alerts'), true)
  assert.equal(operationsTaskSource.includes('sync_operational_notifications'), true)
})

test('scheduled discovery suppresses per-cycle match noise and records scheduler origin', () => {
  assert.equal(discoveryTaskSource.includes('origin != "scheduler"'), true)
  assert.equal(discoveryTaskSource.includes('"_origin": "scheduler"'), true)
  assert.equal(discoveryTaskSource.includes('source_diagnostics'), true)
})
