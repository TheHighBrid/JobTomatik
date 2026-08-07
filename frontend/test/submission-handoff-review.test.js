import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/HandoffReview.jsx', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../src/api/intelligence.js', import.meta.url),
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

test('handoff review is routed and visible in primary navigation', () => {
  assert.equal(appSource.includes("path=\"handoff-review\""), true)
  assert.equal(appSource.includes('element={<HandoffReview />}'), true)
  assert.equal(layoutSource.includes("to: '/handoff-review'"), true)
  assert.equal(layoutSource.includes("label: 'Handoff Review'"), true)
})

test('handoff client uses distinct inspect, create, and review endpoints', () => {
  assert.equal(
    apiSource.includes('api.get(`/intelligence/agent-runs/${runId}/submission-handoff`)'),
    true,
  )
  assert.equal(
    apiSource.includes('api.post(`/intelligence/agent-runs/${runId}/submission-handoff`, data)'),
    true,
  )
  assert.equal(
    apiSource.includes('api.post(`/intelligence/agent-runs/${runId}/submission-handoff/review`, data)'),
    true,
  )
})

test('handoff UI keeps review separate from final-submit approval', () => {
  assert.equal(pageSource.includes('Review is not final-submit approval'), true)
  assert.equal(pageSource.includes('Submission authorized'), true)
  assert.equal(pageSource.includes('Approval issued'), true)
  assert.equal(pageSource.includes('Queue attempted'), true)
  assert.equal(pageSource.includes('CREATE SUBMISSION HANDOFF'), false)
  assert.equal(pageSource.includes('expected_create_acknowledgment'), true)
  assert.equal(pageSource.includes('expected_review_acknowledgment'), true)
  assert.equal(
    pageSource.includes('Final-submit consent is still required separately.'),
    true,
  )
  assert.equal(pageSource.includes('submit_application_task'), false)
})

test('reviewed handoff routes to the exact application only', () => {
  assert.equal(
    pageSource.includes('to={`/applications/${handoff.application_id}`}'),
    true,
  )
  assert.equal(pageSource.includes("handoff.status === 'reviewed'"), true)
})
