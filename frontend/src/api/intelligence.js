import api from './client'

export const getIntelligenceOverview = () => api.get('/intelligence/overview')
export const listCareerMemories = (params = {}) => api.get('/intelligence/memories', { params })
export const createCareerMemory = (data) => api.post('/intelligence/memories', data)
export const deactivateCareerMemory = (id) => api.delete(`/intelligence/memories/${id}`)

export const listRecruiterContacts = (params = {}) => api.get('/intelligence/recruiters', { params })
export const createRecruiterContact = (data) => api.post('/intelligence/recruiters', data)
export const addRecruiterInteraction = (contactId, data) =>
  api.post(`/intelligence/recruiters/${contactId}/interactions`, data)

export const listKnowledgeNodes = (params = {}) =>
  api.get('/intelligence/knowledge/nodes', { params })
export const createKnowledgeNode = (data) => api.post('/intelligence/knowledge/nodes', data)
export const createKnowledgeEdge = (data) => api.post('/intelligence/knowledge/edges', data)

export const recommendSelector = (params) =>
  api.get('/intelligence/selectors/recommendation', { params })
export const recordSelectorOutcome = (data) =>
  api.post('/intelligence/selectors/outcomes', data)
export const listSelectorDiagnostics = (params = {}) =>
  api.get('/intelligence/selectors', { params })
export const updateSelectorControl = (strategyId, data) =>
  api.patch(`/intelligence/selectors/${strategyId}/control`, data)

export const listAgentRuns = (params = {}) => api.get('/intelligence/agent-runs', { params })
export const createAgentRun = (data) => api.post('/intelligence/agent-runs', data)
export const updateAgentTask = (runId, taskId, data) =>
  api.patch(`/intelligence/agent-runs/${runId}/tasks/${taskId}`, data)
export const getAgentExecution = (runId) =>
  api.get(`/intelligence/agent-runs/${runId}/execution`)
export const approveAgentRun = (runId, data) =>
  api.post(`/intelligence/agent-runs/${runId}/approve`, data)
export const rejectAgentRun = (runId, data) =>
  api.post(`/intelligence/agent-runs/${runId}/reject`, data)
export const dispatchAgentRun = (runId) =>
  api.post(`/intelligence/agent-runs/${runId}/dispatch`)
export const pauseAgentRun = (runId, data) =>
  api.post(`/intelligence/agent-runs/${runId}/pause`, data)
export const resumeAgentRun = (runId) =>
  api.post(`/intelligence/agent-runs/${runId}/resume`)
export const cancelAgentRun = (runId, data) =>
  api.post(`/intelligence/agent-runs/${runId}/cancel`, data)
