const LOOPBACK_AND_EMULATOR_HOSTS = new Set([
  'localhost',
  '127.0.0.1',
  '::1',
  '0.0.0.0',
  '10.0.2.2',
  'host.docker.internal',
])

function isPrivateIpv4(hostname) {
  const parts = hostname.split('.').map(Number)
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) {
    return false
  }

  return (
    parts[0] === 10 ||
    (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
    (parts[0] === 192 && parts[1] === 168) ||
    (parts[0] === 169 && parts[1] === 254)
  )
}

export function isLocalApiHostname(hostname) {
  const normalized = String(hostname || '').toLowerCase()
  return (
    LOOPBACK_AND_EMULATOR_HOSTS.has(normalized) ||
    normalized.endsWith('.local') ||
    isPrivateIpv4(normalized)
  )
}

function inferProtocol(value) {
  const parsed = new URL(`http://${value}`)
  return isLocalApiHostname(parsed.hostname) ? 'http://' : 'https://'
}

export function normalizeApiBaseUrl(value, fallback = 'http://127.0.0.1:8010') {
  const trimmed = String(value || '').trim()
  const source = trimmed || fallback
  const withProtocol = /^https?:\/\//i.test(source) ? source : `${inferProtocol(source)}${source}`
  const parsed = new URL(withProtocol)

  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Backend API URL must use HTTP or HTTPS.')
  }
  if (parsed.username || parsed.password) {
    throw new Error('Backend API URL cannot contain embedded credentials.')
  }
  if (parsed.search || parsed.hash) {
    throw new Error('Backend API URL cannot contain a query string or fragment.')
  }
  if (parsed.protocol === 'http:' && !isLocalApiHostname(parsed.hostname)) {
    throw new Error('Remote backend API URLs must use HTTPS to protect authentication tokens.')
  }

  let pathname = parsed.pathname.replace(/\/+$/, '')
  if (pathname.toLowerCase().endsWith('/api')) {
    pathname = pathname.slice(0, -4)
  }

  return `${parsed.protocol}//${parsed.host}${pathname}`
}
