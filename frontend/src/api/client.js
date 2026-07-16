import axios from 'axios'

const DEFAULT_API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const API_URL_STORAGE_KEY = 'jobtomatik_api_url'

const safeLocalStorage = {
  getItem(key) {
    try {
      return window.localStorage.getItem(key)
    } catch {
      return null
    }
  },
  setItem(key, value) {
    try {
      window.localStorage.setItem(key, value)
    } catch {
      // Ignore storage errors in restricted WebViews/private mode.
    }
  },
  removeItem(key) {
    try {
      window.localStorage.removeItem(key)
    } catch {
      // Ignore storage errors in restricted WebViews/private mode.
    }
  },
}

export function normalizeApiBaseUrl(value) {
  const trimmed = String(value || '').trim().replace(/\/+$/, '')
  if (!trimmed) return DEFAULT_API_URL
  if (!/^https?:\/\//i.test(trimmed)) return `https://${trimmed}`
  return trimmed
}

export function getApiBaseUrl() {
  return normalizeApiBaseUrl(safeLocalStorage.getItem(API_URL_STORAGE_KEY) || DEFAULT_API_URL)
}

export function setApiBaseUrl(value) {
  const normalized = normalizeApiBaseUrl(value)
  safeLocalStorage.setItem(API_URL_STORAGE_KEY, normalized)
  api.defaults.baseURL = `${normalized}/api`
  return normalized
}

export function resetApiBaseUrl() {
  safeLocalStorage.removeItem(API_URL_STORAGE_KEY)
  api.defaults.baseURL = `${normalizeApiBaseUrl(DEFAULT_API_URL)}/api`
  return normalizeApiBaseUrl(DEFAULT_API_URL)
}

export function isNetworkError(err) {
  return Boolean(err?.request && !err?.response)
}

export function getApiErrorMessage(err, fallback = 'Request failed') {
  if (isNetworkError(err)) {
    return 'Cannot reach backend API. Open API connection and set the correct backend URL.'
  }

  const detail = err?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || String(item)).join(', ')
  }
  if (detail) return String(detail)
  if (err?.message) return err.message
  return fallback
}

export async function testApiConnection(baseUrl = getApiBaseUrl()) {
  const normalized = normalizeApiBaseUrl(baseUrl)
  const response = await axios.get(`${normalized}/health`, { timeout: 8000 })
  return response.data
}

const api = axios.create({
  baseURL: `${getApiBaseUrl()}/api`,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = safeLocalStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      safeLocalStorage.removeItem('token')
      safeLocalStorage.removeItem('user')
      if (window.location.pathname !== '/login') window.location.href = '/login'
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

// Answer policy vault
export const getAnswerPolicyCatalog = () => api.get('/profile/answer-policies/catalog')
export const listAnswerPolicies = () => api.get('/profile/answer-policies')
export const createAnswerPolicy = (data) => api.post('/profile/answer-policies', data)
export const updateAnswerPolicy = (id, data) => api.patch(`/profile/answer-policies/${id}`, data)
export const confirmAnswerPolicy = (id) => api.post(`/profile/answer-policies/${id}/confirm`)
export const deleteAnswerPolicy = (id) => api.delete(`/profile/answer-policies/${id}`)

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
export const submitApplication = (id, dryRun = true) =>
  api.post(`/applications/${id}/submit?dry_run=${dryRun}`)
export const bulkSubmitApplications = (params) => api.post('/applications/bulk-submit', null, { params })
export const createFollowup = (appId, data) => api.post(`/applications/${appId}/followups`, data)
export const listFollowups = (appId) => api.get(`/applications/${appId}/followups`)

// Notifications
export const getNotifications = (params) => api.get('/notifications', { params })
export const getUnreadCount = () => api.get('/notifications/unread-count')
export const markRead = (id) => api.post(`/notifications/${id}/read`)
export const markAllRead = () => api.post('/notifications/mark-all-read')

// Settings
export const getSettings = () => api.get('/settings')
export const updateSettings = (data) => api.patch('/settings', data)

// Bulk / Auto-pilot
export const bulkApply = (dryRun = true, limit = 20) =>
  api.post(`/jobs/bulk-apply?dry_run=${dryRun}&limit=${limit}`)
export const runAutoPilot = (options = {}) =>
  api.post('/jobs/autopilot', null, { params: { dry_run: true, min_score: 0.55, daily_limit: 15, ...options } })

export default api
