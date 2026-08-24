import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(new URL('../src/pages/AutonomyCenter.jsx', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../src/api/autonomy.js', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
const mobileNavSource = readFileSync(new URL('../src/components/MobileNav.jsx', import.meta.url), 'utf8')


test('autonomy center presents every Day 34 operator domain', () => {
  for (const term of [
    'Readiness',
    'Active adapters',
    'Caps & quiet hours',
    'Queue',
    'Blockers',
    'Handoffs',
    'Evidence',
    'Kill switches',
  ]) {
    assert.equal(pageSource.includes(term), true, `missing Day 34 domain: ${term}`)
  }
})


test('autonomy center exposes pause drain resume and safe rejection without submit', () => {
  for (const term of ['Pause', 'Drain', 'Resume', 'Reject']) {
    assert.equal(pageSource.includes(term), true, `missing operator action: ${term}`)
  }
  assert.equal(pageSource.includes('No direct live-submit control.'), true)
  assert.equal(pageSource.includes('Reject means withdraw from JobTomatik autonomy.'), true)
  assert.equal(apiSource.includes("api.post('/autonomy-control/pause'"), true)
  assert.equal(apiSource.includes("api.post('/autonomy-control/drain'"), true)
  assert.equal(apiSource.includes("api.post('/autonomy-control/resume'"), true)
  assert.equal(apiSource.includes('/autonomy-control/applications/${applicationId}/reject'), true)
  assert.equal(apiSource.includes('/submit'), false)
})


test('autonomy center is offline safe and refreshes on reconnect', () => {
  assert.equal(pageSource.includes("window.addEventListener('online'"), true)
  assert.equal(pageSource.includes("window.addEventListener('offline'"), true)
  assert.equal(pageSource.includes("window.removeEventListener('online'"), true)
  assert.equal(pageSource.includes("window.removeEventListener('offline'"), true)
  assert.equal(pageSource.includes("enabled: online"), true)
  assert.equal(pageSource.includes("disabled={!online"), true)
  assert.equal(pageSource.includes("invalidateQueries({ queryKey: ['autonomy-control'] })"), true)
})


test('autonomy controls include accessible live status and action labels', () => {
  assert.equal(pageSource.includes('aria-live="polite"'), true)
  for (const label of [
    'Pause autonomous processing',
    'Drain autonomy queue without admitting new work',
    'Resume autonomous processing under existing safety gates',
    'Refresh autonomy control status',
  ]) {
    assert.equal(pageSource.includes(label), true, `missing accessibility label: ${label}`)
  }
  assert.equal(pageSource.includes('aria-label={`Reject ${item.title} from autonomy queue`}'), true)
})


test('autonomy control is routed and one tap from the Android tab bar', () => {
  assert.equal(appSource.includes('AutonomyCenter'), true)
  assert.equal(appSource.includes('path="autonomy"'), true)
  assert.equal(mobileNavSource.includes("to: '/autonomy'"), true)
  assert.equal(mobileNavSource.includes("label: 'Control'"), true)
})
