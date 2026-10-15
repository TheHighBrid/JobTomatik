// The image is rendered at its aspect ratio, without object-fit letterboxing.
export function retryableHandoffRead(error) {
  const status = error?.response?.status
  return Boolean(error?.request && !error?.response)
    || status === 408 || status === 429 || status >= 500
}

export function handoffReadErrorMessage(error, fallback) {
  if (retryableHandoffRead(error)) {
    return 'The live view was interrupted. Reconnecting automatically; no browser action or submission will be repeated.'
  }
  return fallback
}

export function handoffPointer(image, clientX, clientY) {
  const rect = image.getBoundingClientRect()
  if (!rect.width || !rect.height || !image.naturalWidth || !image.naturalHeight) return null
  const x = (clientX - rect.left) * image.naturalWidth / rect.width
  const y = (clientY - rect.top) * image.naturalHeight / rect.height
  if (![x, y].every(Number.isFinite) || x < 0 || y < 0 || x >= image.naturalWidth || y >= image.naturalHeight) return null
  return { x, y }
}

export function handoffExpired(session, now = Date.now()) {
  if (!session?.expires_at) return true
  // Legacy SQLite datetimes are UTC even when serialized without an offset.
  const raw = session.expires_at
  const expires = Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(raw) ? raw : `${raw}Z`)
  return !Number.isFinite(expires) || expires <= now
}
