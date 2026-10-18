/** A JT5 recovery-consumed confirmation is not a supervised-pilot acceptance. */
export function isSupervisedPilotReviewEligible(review) {
  return review?.decision === 'accepted'
    && review.valid_for_current_evidence === true
    && typeof review.approval_reference === 'string'
    && review.approval_reference.trim().length > 0
}
