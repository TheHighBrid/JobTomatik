import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const boundary = readFileSync(
  new URL('../src/components/RuntimeUiRevisionBoundary.jsx', import.meta.url),
  'utf8',
)
const app = readFileSync(
  new URL('../src/App.jsx', import.meta.url),
  'utf8',
)

test('authenticated UI always checks its bundled revision against runtime identity', () => {
  assert.equal(app.includes('RuntimeUiRevisionBoundary'), true)
  assert.equal(boundary.includes("api.get('/system/runtime-identity')"), true)
  assert.equal(boundary.includes('VITE_JOBTOMATIK_RUNTIME_REVISION'), true)
  assert.equal(boundary.includes("queryKey: ['runtime-ui-revision-identity']"), true)
})

test('revision mismatch explains the embedded APK boundary instead of claiming an update replaced it', () => {
  assert.equal(boundary.includes('This screen is older than the running JobTomatik runtime.'), true)
  assert.equal(
    boundary.includes('it cannot replace JavaScript embedded inside an already-installed APK'),
    true,
  )
  assert.equal(boundary.includes('UI {shortRevision(state.ui)}'), true)
  assert.equal(boundary.includes('runtime {shortRevision(state.runtime)}'), true)
})

test('mismatched embedded UI offers the exact current localhost route without mutating application state', () => {
  assert.equal(boundary.includes("const LOCAL_RUNTIME_UI_ORIGIN = 'http://127.0.0.1:3000'"), true)
  assert.equal(boundary.includes('window.location.pathname'), true)
  assert.equal(boundary.includes('window.location.search'), true)
  assert.equal(boundary.includes('window.location.hash'), true)
  assert.equal(boundary.includes('Open current runtime UI'), true)
  assert.equal(boundary.includes('target="_blank"'), true)
  assert.equal(boundary.includes('api.post('), false)
})

test('local runtime UI does not offer a self-referential open-current-runtime link', () => {
  assert.equal(boundary.includes('!state.localRuntimeUi && ('), true)
  assert.equal(boundary.includes("replace(/\\/$/, '') === LOCAL_RUNTIME_UI_ORIGIN"), true)
})
