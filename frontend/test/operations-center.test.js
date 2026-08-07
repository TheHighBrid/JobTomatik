import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/OperationsCenter.jsx', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../src/api/operations.js', import.meta.url),
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

test('Operations Center exposes the complete Phase 7 workspace', () => {
  for (const label of [
    'Pipeline',
    'Agenda',
    'Timeline',
    'Compare',
    'Memory',
    'Knowledge',
    'Selector Health',
  ]) {
    assert.equal(pageSource.includes(`label: '${label}'`), true, `${label} tab missing`)
  }
  assert.equal(pageSource.includes('Operations Center'), true)
  assert.equal(pageSource.includes('agenda_days: 14'), true)
})

test('Operations Center remains an inspect-and-correct layer', () => {
  assert.equal(
    pageSource.includes('does not grant application submission or recruiter outreach permission'),
    true,
  )
  assert.equal(pageSource.includes('Save correction'), true)
  assert.equal(pageSource.includes('Queue approved delivery'), false)
  assert.equal(pageSource.includes('Submit application'), false)
})

test('Operations API separates snapshots, memory correction, and graph reads', () => {
  assert.equal(apiSource.includes("api.get('/operations/workspace'"), true)
  assert.equal(apiSource.includes('api.patch(`/operations/memories/${memoryId}`'), true)
  assert.equal(apiSource.includes("api.get('/operations/knowledge/edges'"), true)
})

test('Operations Center is routed from primary navigation', () => {
  assert.equal(appSource.includes("import OperationsCenter from './pages/OperationsCenter'"), true)
  assert.equal(appSource.includes('path="operations"'), true)
  assert.equal(layoutSource.includes("to: '/operations'"), true)
  assert.equal(layoutSource.includes("label: 'Operations Center'"), true)
})
