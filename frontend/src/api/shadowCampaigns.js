import api from './client'

export const getShadowCampaignPreflight = (targetEvidenceType = 'shadow_run_4h') =>
  api.get('/shadow-runs/preflight', { params: { target_evidence_type: targetEvidenceType } })

export const getShadowCampaigns = (params = {}) =>
  api.get('/shadow-runs', { params })

export const getShadowCampaign = (sessionId) =>
  api.get(`/shadow-runs/${sessionId}`)

export const startShadowCampaign = (data) =>
  api.post('/shadow-runs', data, { timeout: 12 * 60 * 1000 })

export const stopShadowCampaign = (sessionId, data) =>
  api.post(`/shadow-runs/${sessionId}/stop`, data)

export const recordShadowCampaignEvidence = (sessionId) =>
  api.post(`/shadow-runs/${sessionId}/record-evidence`)
