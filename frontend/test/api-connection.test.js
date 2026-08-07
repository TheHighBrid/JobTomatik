import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  ANDROID_TERMUX_API_URL,
  getApiRoutingErrorMessage,
  isApiConfigurationError,
  isLikelyFrontendApiUrl,
  validateJobTomatikHealth,
} from '../src/api/connection.js'

const connectionSource = readFileSync(
  new URL('../src/api/connection.js', import.meta.url),
  'utf8',
)
const clientSource = readFileSync(
  new URL('../src/api/client.js', import.meta.url),
  'utf8',
)
const fieldSource = readFileSync(
  new URL('../src/components/ApiBaseUrlField.jsx', import.meta.url),
  'utf8',
)
const loginSource = readFileSync(
  new URL('../src/pages/Login.jsx', import.meta.url),
  'utf8',
)
const registerSource = readFileSync(
  new URL('../src/pages/Register.jsx', import.meta.url),
  'utf8',
)

test('Android connection helper identifies the frontend port and canonical Termux backend', () => {
  assert.equal(ANDROID_TERMUX_API_URL, 'http://127.0.0.1:8010')
  assert.equal(isLikelyFrontendApiUrl('http://10.0.0.231:3000'), true)
  assert.equal(isLikelyFrontendApiUrl('http://127.0.0.1:8010'), false)
  assert.equal(isLikelyFrontendApiUrl('http://192.168.1.25:8000'), false)
})

test('health validation accepts only the exact JobTomatik API identity', () => {
  const valid = { status: 'ok', service: 'JobTomatik API', version: '1.0.0' }
  assert.equal(validateJobTomatikHealth(valid), valid)
  assert.throws(
    () => validateJobTomatikHealth('<html>frontend</html>'),
    /not the JobTomatik backend API/,
  )
  assert.throws(
    () => validateJobTomatikHealth({ status: 'ok', service: 'Vite' }),
    /not the JobTomatik backend API/,
  )
})

test('frontend routing failures produce a direct Android correction', () => {
  const error = { response: { status: 500 } }
  const message = getApiRoutingErrorMessage(error, 'http://10.0.0.231:3000')
  assert.match(message, /Port 3000 is the JobTomatik frontend/)
  assert.match(message, /http:\/\/127\.0\.0\.1:8010/)
  assert.equal(isApiConfigurationError(error, 'http://10.0.0.231:3000'), true)
})

test('connection test uses the backend-specific health endpoint', () => {
  assert.equal(connectionSource.includes('/api/system/health'), true)
  assert.equal(connectionSource.includes("error.code = 'JOBTOMATIK_FRONTEND_URL'"), true)
  assert.equal(connectionSource.includes('validateJobTomatikHealth(response.data)'), true)
})

test('Android client migrates stale loopback backend ports to managed 8010', () => {
  assert.equal(clientSource.includes("ANDROID_TERMUX_API_URL = 'http://127.0.0.1:8010'"), true)
  assert.equal(clientSource.includes('reconcileAndroidApiBaseUrl'), true)
  assert.equal(clientSource.includes("parsed.port !== '8010'"), true)
  assert.equal(clientSource.includes('safeLocalStorage.setItem(API_URL_STORAGE_KEY, normalized)'), true)
})

test('every API request re-evaluates the managed Android backend route', () => {
  assert.equal(
    clientSource.includes('config.baseURL = `${getApiBaseUrl()}/api`'),
    true,
  )
})

test('auth screens expose and explain API routing failures', () => {
  assert.equal(fieldSource.includes('Use Android backend'), true)
  assert.equal(fieldSource.includes('Port 3000 is the JobTomatik frontend'), true)
  assert.equal(fieldSource.includes('testJobTomatikApiConnection'), true)
  assert.equal(loginSource.includes('getApiRoutingErrorMessage'), true)
  assert.equal(loginSource.includes('isApiConfigurationError'), true)
  assert.equal(registerSource.includes('getApiRoutingErrorMessage'), true)
  assert.equal(registerSource.includes('isApiConfigurationError'), true)
})
