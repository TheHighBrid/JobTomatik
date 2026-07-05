import { useState } from 'react'
import { getApiBaseUrl, resetApiBaseUrl, setApiBaseUrl } from '../api/client'

export default function ApiBaseUrlField({ compact = false }) {
  const [value, setValue] = useState(getApiBaseUrl())
  const [saved, setSaved] = useState(false)

  const save = () => {
    const normalized = setApiBaseUrl(value)
    setValue(normalized)
    setSaved(true)
    window.setTimeout(() => setSaved(false), 1800)
  }

  const reset = () => {
    const fallback = resetApiBaseUrl()
    setValue(fallback)
    setSaved(true)
    window.setTimeout(() => setSaved(false), 1800)
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
      <div className="flex items-center gap-2">
        <button type="button" onClick={save} className="btn-secondary text-xs px-3 py-2">
          Save API URL
        </button>
        <button type="button" onClick={reset} className="text-xs text-gray-500 hover:text-gray-800">
          Reset
        </button>
        {saved && <span className="text-xs text-green-600">Saved</span>}
      </div>
      <p className="text-xs text-gray-500 leading-relaxed">
        For an Android APK, this must be a backend your phone can reach. Use a deployed HTTPS API URL, or your computer's LAN IP during local testing.
      </p>
    </div>
  )
}
