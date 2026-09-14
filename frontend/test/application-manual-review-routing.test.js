import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canOpenManualReviewPage,
  duplicateOwnerApplicationId,
  routeApplicationManualReviews,
} from '../src/applicationManualReviewRouting.js'

function review(id, reason_code, created_at, blocking_url = 'https://jobs.lever.co/example/posting/apply', details = {}) {
  return {
    id,
    reason_code,
    created_at,
    blocking_url,
    details,
    status: 'open',
    summary: 'Manual review required.',
  }
}

test('retained browser challenge stays visible when a newer policy review coexists', () => {
  const routed = routeApplicationManualReviews([
    review(1, 'captcha_detected', '2026-09-07T17:00:00Z'),
    review(2, 'ambiguous_question', '2026-09-07T17:01:00Z'),
  ])

  assert.equal(routed.activeManualReview.reason_code, 'captcha_detected')
  assert.equal(routed.activeHandoffReview.reason_code, 'captcha_detected')
  assert.equal(routed.handoffExpected, true)
})

test('operator final-submit boundary outranks older or newer review noise', () => {
  const routed = routeApplicationManualReviews([
    review(1, 'captcha_detected', '2026-09-07T17:00:00Z'),
    review(2, 'operator_final_submit_required', '2026-09-07T17:01:00Z'),
    review(3, 'ambiguous_question', '2026-09-07T17:02:00Z'),
  ])

  assert.equal(routed.activeManualReview.reason_code, 'operator_final_submit_required')
  assert.equal(routed.operatorFinalSubmitReview.reason_code, 'operator_final_submit_required')
  assert.equal(routed.handoffExpected, false)
})

test('Lever supervised reviews never expose a direct employer-page escape', () => {
  assert.equal(
    canOpenManualReviewPage(review(1, 'ambiguous_question', '2026-09-07T17:00:00Z'), 'lever'),
    false,
  )
  assert.equal(
    canOpenManualReviewPage(review(2, 'captcha_detected', '2026-09-07T17:00:00Z'), 'lever'),
    false,
  )
})

test('resumable browser challenges never expose a second-page escape on other platforms', () => {
  assert.equal(
    canOpenManualReviewPage(review(1, 'mfa_required', '2026-09-07T17:00:00Z'), 'greenhouse'),
    false,
  )
  assert.equal(
    canOpenManualReviewPage(review(2, 'automation_error', '2026-09-07T17:00:00Z'), 'greenhouse'),
    true,
  )
})

test('duplicate submission identity routes to the canonical local application', () => {
  const duplicate = review(
    4,
    'safety_gate_blocked',
    '2026-09-08T06:00:00Z',
    'https://jobs.lever.co/eqbank/posting/apply',
    {
      reason: 'duplicate_submission_identity',
      existing_application_id: 137,
      alias_type: 'verified_platform_posting',
    },
  )
  const routed = routeApplicationManualReviews([duplicate])

  assert.equal(duplicateOwnerApplicationId(duplicate), 137)
  assert.equal(routed.activeManualReview.blocking_url, '/applications/137')
  assert.match(routed.activeManualReview.summary, /canonical application #137/)
  assert.equal(canOpenManualReviewPage(routed.activeManualReview, 'lever'), true)
})

test('duplicate routing fails closed without a valid canonical application id', () => {
  const malformed = review(
    5,
    'safety_gate_blocked',
    '2026-09-08T06:01:00Z',
    'https://jobs.lever.co/eqbank/posting/apply',
    {
      reason: 'duplicate_submission_identity',
      existing_application_id: 'not-an-id',
    },
  )
  const routed = routeApplicationManualReviews([malformed])

  assert.equal(duplicateOwnerApplicationId(malformed), null)
  assert.equal(routed.activeManualReview.blocking_url, 'https://jobs.lever.co/eqbank/posting/apply')
  assert.equal(canOpenManualReviewPage(routed.activeManualReview, 'lever'), false)
})