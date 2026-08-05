import { useState } from 'react'
import {
  getApiBaseUrl,
  getApiErrorMessage,
  resetApiBaseUrl,
  setApiBaseUrl,
} from '../api/client'
import {
  ANDROID_TERMUX_API_URL,
  getApiRoutingErrorMessage,
  isLikelyFrontendApiUrl,
  testJobTomatikApiConnection,
} from '../api/connection'

export default function ApiBaseUrlField({ compact = false }) {
  const [value, setValue] = useState(getApiBaseUrl())
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const frontendUrlSelected = isLikelyFrontendApiUrl(value)

  const markSaved = () => {
    setSaved(true)
    window.setTimeout(() => setSaved(false), 1800)
  }

  const save = () => {
    try {
      const normalized = setApiBaseUrl(value)
      setValue(normalized)
      markSaved()
      setTestResult(null)
      return normalized
    } catch (error) {
      setSaved(false)
      setTestResult({ ok: false, message: error.message || 'Invalid backend API URL.' })
      return null
    }
  }

  const useAndroidBackend = () => {
    const normalized = setApiBaseUrl(ANDROID_TERMUX_API_URL)
    setValue(normalized)
    setTestResult(null)
    markSaved()
  }

  const reset = () => {
    const fallback = resetApiBaseUrl()
    setValue(fallback)
    markSaved()
    setTestResult(null)
  }

  const test = async () => {
    const normalized = save()
    if (!normalized) return

    setTesting(true)
    setTestResult(null)
    try {
      const data = await testJobTomatikApiConnection(normalized)
      setTestResult({
        ok: true,
        message: `Connected to ${data.service}.`,
      })
    } catch (err) {
      setTestResult({
        ok: false,
        message: (
          getApiRoutingErrorMessage(err, normalized) ||
          getApiErrorMessage(err, 'Backend API test failed.')
        ),
      })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      <div>
        <label className="label" htmlFor="backend-api-url">Backend API URL</label>
        <input
          id="backend-api-url"
          type="url"
          inputMode="url"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck="false"
          className="input"
          placeholder="https://api.your-domain.com"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && save()}
        />
      </div>
      {frontendUrlSelected && (
        <div className="rounded-xl border border-amber-400/40 bg-amber-400/10 p-3 text-xs leading-relaxed text-amber-100" role="alert">
          <p>
            Port 3000 is the JobTomatik frontend. The Android/Termux backend runs at{' '}
            <span className="font-semibold">{ANDROID_TERMUX_API_URL}</span>.
          </p>
          <button
            type="button"
            onClick={useAndroidBackend}
            className="mt-2 font-semibold text-brand-gold hover:underline"
          >
            Use Android backend
          </button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} className="btn-secondary text-xs px-3 py-2">
          Save API URL
        </button>
        <button
          type="button"
          onClick={test}
          disabled={testing}
          className="btn-primary text-xs px-3 py-2 disabled:opacity-60"
        >
          {testing ? 'Testing…' : 'Test connection'}
        </button>
        <button type="button" onClick={reset} className="text-xs text-gray-500 hover:text-gray-800">
          Reset
        </button>
        {saved && <span className="text-xs text-green-600" role="status">Saved</span>}
      </div>
      {testResult && (
        <p
          className={testResult.ok ? 'text-xs text-green-700' : 'text-xs text-red-600'}
          role="status"
          aria-live="polite"
        >
          {testResult.message}
        </p>
      )}
      <p className="text-xs text-gray-500 leading-relaxed">
        For an Android APK, this must be the direct backend URL, not the frontend on port 3000. The same-device Termux default is {ANDROID_TERMUX_API_URL}. Local and private-network addresses may use HTTP during development. Any public or remote backend must use HTTPS.
      </p>
    </div>
  )
}
