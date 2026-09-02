import api from './client'

export const getOperatorAssistedPreflight = (applicationId) =>
  api.get(`/supervised-submissions/applications/${applicationId}/operator-assisted/preflight`)

export const prepareOperatorAssistedSubmission = (applicationId) =>
  api.post(`/supervised-submissions/applications/${applicationId}/operator-assisted/prepare`)

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
