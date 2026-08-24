import api from './client'

export const getAutonomyControlSnapshot = () => api.get('/autonomy-control/snapshot')
export const pauseAutonomy = (reason = '') => api.post('/autonomy-control/pause', { reason })
export const drainAutonomyQueue = (reason = '') => api.post('/autonomy-control/drain', { reason })
export const resumeAutonomy = (reason = '') => api.post('/autonomy-control/resume', { reason })
export const rejectAutonomyApplication = (applicationId, reason = '') => (
  api.post(`/autonomy-control/applications/${applicationId}/reject`, { reason })
)
