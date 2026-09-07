export const HANDOFF_REVIEW_REASONS = new Set([
  'captcha_detected',
  'mfa_required',
  'login_required',
  'anti_bot_challenge',
])

const OPEN_REVIEW_STATUSES = new Set(['open', 'in_progress'])

function createdAtMs(review) {
  const value = new Date(review?.created_at || 0).getTime()
  return Number.isFinite(value) ? value : 0
}

export function routeApplicationManualReviews(reviews = []) {
  const openManualReviews = [...(reviews || [])]
    .filter((review) => OPEN_REVIEW_STATUSES.has(review?.status))
    .sort((a, b) => createdAtMs(b) - createdAtMs(a))

  const operatorFinalSubmitReview = openManualReviews.find(
    (review) => review.reason_code === 'operator_final_submit_required',
  ) || null
  const activeHandoffReview = openManualReviews.find(
    (review) => HANDOFF_REVIEW_REASONS.has(review.reason_code),
  ) || null

  // Consequential browser boundaries outrank generic policy/review rows. In
  // particular, a coexisting ambiguous-question row must never hide a retained
  // CAPTCHA/MFA/login handoff, and a final-submit review must outrank both.
  const activeManualReview = (
    operatorFinalSubmitReview
    || activeHandoffReview
    || openManualReviews[0]
    || null
  )

  return {
    openManualReviews,
    activeManualReview,
    operatorFinalSubmitReview,
    activeHandoffReview,
    handoffExpected: Boolean(
      !operatorFinalSubmitReview
      && (!activeManualReview || activeHandoffReview)
    ),
  }
}

export function canOpenManualReviewPage(review, supervisedPlatform) {
  if (!review?.blocking_url) return false
  if (supervisedPlatform === 'lever') return false
  if (review.reason_code === 'application_target_required') return false
  if (review.reason_code === 'operator_final_submit_required') return false
  if (HANDOFF_REVIEW_REASONS.has(review.reason_code)) return false
  return true
}
