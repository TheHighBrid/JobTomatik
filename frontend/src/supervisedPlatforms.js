const PLATFORM_CONFIG = Object.freeze({
  greenhouse: Object.freeze({
    key: 'greenhouse',
    displayName: 'Greenhouse',
    pilotFlagName: 'GREENHOUSE_SUPERVISED_PILOT_ENABLED',
    pilotSwitchLabel: 'Greenhouse pilot switch',
  }),
  lever: Object.freeze({
    key: 'lever',
    displayName: 'Lever',
    pilotFlagName: 'LEVER_SUPERVISED_PILOT_ENABLED',
    pilotSwitchLabel: 'Lever pilot switch',
  }),
})

const COMMON_BLOCKER_LABELS = Object.freeze({
  global_live_submit_disabled: 'The global real-submission switch is off.',
  application_not_ready_to_apply: 'The application is not in the ready-to-apply state.',
  unresolved_manual_reviews: 'Resolve every open manual-review task first.',
  missing_application_url: 'The exact application URL is missing.',
  missing_submission_idempotency_key: 'The duplicate-prevention key is missing.',
  resume_missing_or_unreadable: 'The selected résumé is missing or unreadable.',
  target_identity_unverified: 'The exact ATS target identity could not be verified.',
  target_identity_mismatch: 'The current ATS target no longer matches the approved identity.',
  official_posting_metadata_unavailable: 'Official posting metadata is unavailable.',
  official_posting_inactive: 'The official posting is no longer active.',
  application_target_closed_or_expired: 'The exact application posting is closed or expired.',
  application_target_liveness_unverified: 'The exact application posting could not be re-verified. Try again when the target is reachable.',
})

const PLATFORM_BLOCKER_LABELS = Object.freeze({
  greenhouse_supervised_pilot_disabled: 'The Greenhouse supervised-pilot switch is off.',
  lever_supervised_pilot_disabled: 'The Lever supervised-pilot switch is off.',
})

export function normalizeSupervisedPlatform(value) {
  const platform = String(value || '').trim().toLowerCase()
  return PLATFORM_CONFIG[platform] ? platform : null
}

export function getSupervisedPlatformConfig(value) {
  const platform = normalizeSupervisedPlatform(value)
  return platform ? PLATFORM_CONFIG[platform] : null
}

export function detectSupervisedPlatform(value) {
  let hostname = ''
  try {
    hostname = new URL(String(value || '')).hostname.toLowerCase()
  } catch {
    const text = String(value || '').toLowerCase()
    if (/jobs\.eu\.lever\.co/.test(text) || /jobs\.lever\.co/.test(text)) return 'lever'
    if (/greenhouse\.io/.test(text)) return 'greenhouse'
    return null
  }

  if (hostname === 'jobs.lever.co' || hostname === 'jobs.eu.lever.co') return 'lever'
  if (hostname === 'greenhouse.io' || hostname.endsWith('.greenhouse.io')) return 'greenhouse'
  return null
}

export function isSupervisedApplicationUrl(value) {
  return Boolean(detectSupervisedPlatform(value))
}

export function supervisedBlockerLabel(blocker, platformValue) {
  const blockerKey = String(blocker || '').trim()
  const platform = getSupervisedPlatformConfig(platformValue)

  if (COMMON_BLOCKER_LABELS[blockerKey]) return COMMON_BLOCKER_LABELS[blockerKey]
  if (PLATFORM_BLOCKER_LABELS[blockerKey]) return PLATFORM_BLOCKER_LABELS[blockerKey]
  if (blockerKey === 'unsupported_platform') {
    return platform
      ? `This application is not a supported ${platform.displayName} target.`
      : 'This application is not a registered supervised-submission target.'
  }
  return blockerKey.replaceAll('_', ' ')
}

export function shortHash(value, startLength = 12, endLength = 8) {
  const text = String(value || '').trim()
  if (!text) return 'Unavailable'
  if (text.length <= startLength + endLength + 1) return text
  return `${text.slice(0, startLength)}…${text.slice(-endLength)}`
}

export function readLeverTargetIdentity(preflight) {
  const target = preflight?.target_identity || {}
  return {
    site: String(target.site || target.board_token || '').trim(),
    postingId: String(target.posting_id || target.job_id || '').trim(),
    region: String(target.region || '').trim().toLowerCase(),
    canonicalUrl: String(
      target.canonical_apply_url
      || target.canonical_application_url
      || preflight?.application_url
      || '',
    ).trim(),
    postingMetadataHash: String(target.posting_metadata_hash || '').trim(),
    targetIdentityHash: String(
      preflight?.target_identity_hash
      || target.target_identity_hash
      || '',
    ).trim(),
    adapterVersion: String(preflight?.adapter_version || target.adapter_version || '').trim(),
    verified: preflight?.target_identity_verified === true,
  }
}

export const SUPERVISED_PLATFORM_KEYS = Object.freeze(Object.keys(PLATFORM_CONFIG))
