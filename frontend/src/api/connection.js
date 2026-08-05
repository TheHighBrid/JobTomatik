import axios from 'axios'

import { normalizeApiBaseUrl } from './url'

export const JOBTOMATIK_API_SERVICE = 'JobTomatik API'
export const ANDROID_TERMUX_API_URL = 'http://127.0.0.1:8010'

function parseApiUrl(value) {
  try {
    return new URL(normalizeApiBaseUrl(value, ANDROID_TERMUX_API_URL))
  } catch {
    return null
  }
}

export function isLikelyFrontendApiUrl(value) {
  const parsed = parseApiUrl(value)
  return parsed?.port === '3000'
}

export function validateJobTomatikHealth(payload) {
  const valid = (
    payload &&
    typeof payload === 'object' &&
    payload.status === 'ok' &&
    payload.service === JOBTOMATIK_API_SERVICE
  )

  if (!valid) {
    const error = new Error('The saved URL is reachable, but it is not the JobTomatik backend API.')
    error.code = 'JOBTOMATIK_API_MISMATCH'
    throw error
  }

  return payload
}

export function getApiRoutingErrorMessage(error, baseUrl) {
  if (error?.code === 'JOBTOMATIK_FRONTEND_URL' || isLikelyFrontendApiUrl(baseUrl)) {
    return (
      `Port 3000 is the JobTomatik frontend, not the backend API. ` +
      `For the Android/Termux backend, use ${ANDROID_TERMUX_API_URL}, then tap Test connection.`
    )
  }

  if (error?.code === 'JOBTOMATIK_API_MISMATCH') {
    return (
      'The saved URL responded, but it did not identify itself as JobTomatik API. ' +
      'Open API connection and enter the direct backend URL.'
    )
  }

  return null
}

export function isApiConfigurationError(error, baseUrl) {
  return Boolean(getApiRoutingErrorMessage(error, baseUrl))
}

export async function testJobTomatikApiConnection(baseUrl) {
  const normalized = normalizeApiBaseUrl(baseUrl, ANDROID_TERMUX_API_URL)

  if (isLikelyFrontendApiUrl(normalized)) {
    const error = new Error('The configured URL points to the frontend development server.')
    error.code = 'JOBTOMATIK_FRONTEND_URL'
    throw error
  }

  const response = await axios.get(`${normalized}/api/system/health`, { timeout: 8000 })
  return validateJobTomatikHealth(response.data)
}
