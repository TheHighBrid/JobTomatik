import api from './client'

export const getCertificationManifest = (params = {}) =>
  api.get('/certification/manifest', { params })

export const getCertificationEvidence = (params = {}) =>
  api.get('/certification/evidence', { params })

export const recordCertificationEvidence = (data) =>
  api.post('/certification/evidence', data)

export const verifyCertificationEvidence = (evidenceId, data) =>
  api.post(`/certification/evidence/${evidenceId}/verify`, data)

export const authorizeCertificationTrack = (data) =>
  api.post('/certification/authorizations', data)

export const revokeCertificationAuthorization = (authorizationId, data) =>
  api.post(`/certification/authorizations/${authorizationId}/revoke`, data)
