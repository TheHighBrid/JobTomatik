import api from './client'

export const getSchedulerPreview = (params = {}) => api.get('/scheduler/preview', { params })
export const runSchedulerCycle = () => api.post('/scheduler/run')
