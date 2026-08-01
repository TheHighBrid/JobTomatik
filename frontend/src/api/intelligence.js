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

export const listAgentRuns = (params = {}) => api.get('/intelligence/agent-runs', { params })
export const createAgentRun = (data) => api.post('/intelligence/agent-runs', data)
export const updateAgentTask = (runId, taskId, data) =>
  api.patch(`/intelligence/agent-runs/${runId}/tasks/${taskId}`, data)
