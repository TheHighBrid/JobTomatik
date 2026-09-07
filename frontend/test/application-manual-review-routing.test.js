import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canOpenManualReviewPage,
  routeApplicationManualReviews,
} from '../src/applicationManualReviewRouting.js'

function review(id, reason_code, created_at, blocking_url = 'https://jobs.lever.co/example/posting/apply') {
  return {
    id,
    reason_code,
    created_at,
    blocking_url,
    status: 'open',
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
