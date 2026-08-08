import api from './client'

export const getPostApplicationWorkspace = () => api.get('/post-application/workspace')

export const ingestEmployerMessage = (applicationId, data) =>
  api.post(`/post-application/applications/${applicationId}/messages`, data)

export const confirmEmployerMessageStatus = (applicationId, eventId, acknowledgment) =>
  api.post(`/post-application/applications/${applicationId}/messages/${eventId}/apply-status`, {
    acknowledgment,
  })

export const schedulePostApplicationInterview = (applicationId, data) =>
  api.post(`/post-application/applications/${applicationId}/interview`, data)

export const getInterviewPrep = (applicationId) =>
  api.get(`/post-application/applications/${applicationId}/interview-prep`)

export const recordPostApplicationOutcome = (applicationId, data) =>
  api.post(`/post-application/applications/${applicationId}/outcome`, data)

export const getOfferComparison = () => api.get('/post-application/offers')
