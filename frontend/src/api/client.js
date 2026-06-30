import axios from 'axios'

export function getBaseUrl() {
  return localStorage.getItem('api_url') || import.meta.env.VITE_API_URL || 'http://localhost:8000'
}

const api = axios.create({
  baseURL: `${getBaseUrl()}/api`,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  // Re-read baseURL on every request so runtime URL changes take effect
  config.baseURL = `${getBaseUrl()}/api`
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

// Auth
export const login = (email, password) =>
  api.post('/auth/login', new URLSearchParams({ username: email, password }), {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })

export const register = (data) => api.post('/auth/register', data)

// Profile
export const getProfile = () => api.get('/profile')
export const updateProfile = (data) => api.patch('/profile', data)
export const uploadResume = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/profile/resume', form, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const deleteResume = () => api.delete('/profile/resume')

// Jobs
export const searchJobs = (params) => api.post('/jobs/search', params)
export const getJobQueue = (params) => api.get('/jobs/queue', { params })
export const listJobs = (params) => api.get('/jobs', { params })
export const getJob = (id) => api.get(`/jobs/${id}`)
export const approveJob = (id) => api.post(`/jobs/${id}/approve`)
export const rejectJob = (id) => api.post(`/jobs/${id}/reject`)
export const getTaskStatus = (taskId) => api.get(`/jobs/task/${taskId}/status`)

// Applications
export const createApplication = (data) => api.post('/applications', data)
export const listApplications = (params) => api.get('/applications', { params })
export const getApplicationStats = () => api.get('/applications/stats')
export const getApplication = (id) => api.get(`/applications/${id}`)
export const updateApplication = (id, data) => api.patch(`/applications/${id}`, data)
export const generateCoverLetter = (id) => api.post(`/applications/${id}/generate-cover-letter`)
export const submitApplication = (id, dryRun = false) =>
  api.post(`/applications/${id}/submit?dry_run=${dryRun}`)
export const createFollowup = (appId, data) => api.post(`/applications/${appId}/followups`, data)
export const listFollowups = (appId) => api.get(`/applications/${appId}/followups`)

// Notifications
export const getNotifications = (params) => api.get('/notifications', { params })
export const getUnreadCount = () => api.get('/notifications/unread-count')
export const markRead = (id) => api.post(`/notifications/${id}/read`)
export const markAllRead = () => api.post('/notifications/mark-all-read')

export default api
