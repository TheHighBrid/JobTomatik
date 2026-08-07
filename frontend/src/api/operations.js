import api from './client'

export const getOperationsWorkspace = (params = {}) =>
  api.get('/operations/workspace', { params })

export const correctCareerMemory = (memoryId, data) =>
  api.patch(`/operations/memories/${memoryId}`, data)

export const listOperationsKnowledgeEdges = (params = {}) =>
  api.get('/operations/knowledge/edges', { params })
