import { useState } from 'react'
import {
  getApiBaseUrl,
  getApiErrorMessage,
  resetApiBaseUrl,
  setApiBaseUrl,
  testApiConnection,
} from '../api/client'

export default function ApiBaseUrlField({ compact = false }) {
  const [value, setValue] = useState(getApiBaseUrl())
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  const save = () => {
    const normalized = setApiBaseUrl(value)
    setValue(normalized)
    setSaved(true)
    setTestResult(null)
    window.setTimeout(() => setSaved(false), 1800)
    return normalized
  }

  const reset = () => {
    const fallback = resetApiBaseUrl()
    setValue(fallback)
    setSaved(true)
    setTestResult(null)
    window.setTimeout(() => setSaved(false), 1800)
  }

  const test = async () => {
    const normalized = save()
    setTesting(true)
    setTestResult(null)
    try {
      const data = await testApiConnection(normalized)
      setTestResult({
        ok: true,
        message: data?.service ? `Connected to ${data.service}.` : 'Backend API is reachable.',
      })
    } catch (err) {
      setTestResult({ ok: false, message: getApiErrorMessage(err, 'Backend API test failed.') })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      <div>
        <label className="label">Backend API URL</label>
        <input
          type="url"
          className="input"
          placeholder="https://api.your-domain.com"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && save()}
        />
      </div>
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
        {saved && <span className="text-xs text-green-600">Saved</span>}
      </div>
      {testResult && (
        <p className={testResult.ok ? 'text-xs text-green-700' : 'text-xs text-red-600'}>
          {testResult.message}
        </p>
      )}
      <p className="text-xs text-gray-500 leading-relaxed">
        For an Android APK, this must be a backend your phone can reach. On Android, localhost only works if the backend is running on this same device. Use a deployed HTTPS API URL, or your computer&apos;s LAN IP during local testing.
      </p>
    </div>
  )
}
