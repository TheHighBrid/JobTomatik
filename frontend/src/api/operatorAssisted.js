import api from './client'

export const getOperatorAssistedPreflight = (applicationId) =>
  api.get(`/supervised-submissions/applications/${applicationId}/operator-assisted/preflight`)

export const prepareOperatorAssistedSubmission = (applicationId, { submitWhenReady = false } = {}) =>
  api.post(`/supervised-submissions/applications/${applicationId}/operator-assisted/prepare`, {
    submit_when_ready: submitWhenReady,
  })

export const completeOperatorAssistedSubmission = (applicationId, completionRequestId) =>
  api.post(`/supervised-submissions/applications/${applicationId}/operator-assisted/complete`, {
    completion_request_id: completionRequestId,
  }, { timeout: 180_000 })

export const revalidateAnswerPolicyReview = (applicationId, reviewId) =>
  api.post(
    `/applications/${applicationId}/manual-reviews/${reviewId}/revalidate-answer-policies`,
  )

export const retireStaleAnswerPolicyReviewForReprepare = (applicationId, reviewId) =>
  api.post(
    `/applications/${applicationId}/manual-reviews/${reviewId}/retire-stale-for-reprepare`,
  )

export const createOperatorAssistedApproval = (applicationId, data) =>
  api.post(`/supervised-submissions/applications/${applicationId}/operator-assisted/approvals`, data)

export const authorizeOperatorFinalClick = (applicationId, reference) =>
  api.post(
    `/supervised-submissions/applications/${applicationId}/operator-assisted/approvals/${reference}/authorize-final-click`,
  )

export const submitOperatorAssistedFinalAction = (applicationId, handoffPublicId, leaseToken) =>
  api.post(
    `/supervised-submissions/applications/${applicationId}/operator-assisted/handoffs/${handoffPublicId}/submit`,
    { lease_token: leaseToken },
  )
