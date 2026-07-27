function getLocalStorage() {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

export const safeLocalStorage = {
  getItem(key) {
    try {
      return getLocalStorage()?.getItem(key) ?? null
    } catch {
      return null
    }
  },
  setItem(key, value) {
    try {
      getLocalStorage()?.setItem(key, value)
      return true
    } catch {
      return false
    }
  },
  removeItem(key) {
    try {
      getLocalStorage()?.removeItem(key)
      return true
    } catch {
      return false
    }
  },
}

export function readStoredJson(key, fallback = null) {
  const value = safeLocalStorage.getItem(key)
  if (!value) return fallback

  try {
    return JSON.parse(value)
  } catch {
    safeLocalStorage.removeItem(key)
    return fallback
  }
}
