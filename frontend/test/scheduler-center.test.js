import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/SchedulerCenter.jsx', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../src/api/scheduler.js', import.meta.url),
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

test('scheduler center states the autonomous safety boundary explicitly', () => {
  assert.equal(pageSource.includes('Scheduler policy is not submission permission.'), true)
  assert.equal(pageSource.includes('certified_autonomous'), true)
  assert.equal(pageSource.includes('CAPTCHA, MFA, identity checks, assessments'), true)
})

test('scheduler center exposes full bounded policy authoring', () => {
  for (const term of [
    'Scheduled discovery',
    'Autonomous candidate processing',
    'Dry-run mode',
    'Daily cap',
    'Weekly cap',
    'Per-employer daily cap',
    'Quiet hours start UTC',
    'Employer allow list',
    'Employer exclude list',
    'Allowed locations',
    'Allowed seniority',
    'Allowed languages',
    'Minimum salary',
    'Autonomous platform opt-in',
  ]) {
    assert.equal(pageSource.includes(term), true, `missing policy control: ${term}`)
  }
})

test('scheduler page explains candidate priority and exact policy decisions', () => {
  assert.equal(pageSource.includes('Candidate queue preview'), true)
  assert.equal(pageSource.includes('priority_score'), true)
  assert.equal(pageSource.includes('policy_decision'), true)
  assert.equal(pageSource.includes('days_remaining'), true)
})

test('scheduler API has separate read preview and bounded run actions', () => {
  assert.equal(apiSource.includes("api.get('/scheduler/preview'"), true)
  assert.equal(apiSource.includes("api.post('/scheduler/run'"), true)
})

test('scheduler center is routed and present in primary navigation', () => {
  assert.equal(appSource.includes('SchedulerCenter'), true)
  assert.equal(appSource.includes('path="scheduler"'), true)
  assert.equal(layoutSource.includes("to: '/scheduler'"), true)
  assert.equal(layoutSource.includes("label: 'Scheduler Center'"), true)
})
