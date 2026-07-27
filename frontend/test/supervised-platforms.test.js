import assert from 'node:assert/strict'
import test from 'node:test'

import {
  detectSupervisedPlatform,
  getSupervisedPlatformConfig,
  readLeverTargetIdentity,
  shortHash,
  supervisedBlockerLabel,
} from '../src/supervisedPlatforms.js'

test('supervised URL detection covers Greenhouse and both Lever regions', () => {
  assert.equal(
    detectSupervisedPlatform('https://job-boards.greenhouse.io/example/jobs/123'),
    'greenhouse',
  )
  assert.equal(
    detectSupervisedPlatform('https://jobs.lever.co/example/abc/apply'),
    'lever',
  )
  assert.equal(
    detectSupervisedPlatform('https://jobs.eu.lever.co/example/abc/apply'),
    'lever',
  )
  assert.equal(detectSupervisedPlatform('https://example.com/jobs/123'), null)
  assert.equal(detectSupervisedPlatform('https://fake-jobs.lever.co.example.com/123'), null)
})

test('platform configuration exposes exact pilot flag labels', () => {
  assert.deepEqual(getSupervisedPlatformConfig('lever'), {
    key: 'lever',
    displayName: 'Lever',
    pilotFlagName: 'LEVER_SUPERVISED_PILOT_ENABLED',
    pilotSwitchLabel: 'Lever pilot switch',
  })
  assert.equal(getSupervisedPlatformConfig('workday'), null)
})

test('blocker labels remain platform-specific and fail closed for unknown targets', () => {
  assert.equal(
    supervisedBlockerLabel('lever_supervised_pilot_disabled', 'lever'),
    'The Lever supervised-pilot switch is off.',
  )
  assert.equal(
    supervisedBlockerLabel('unsupported_platform', 'lever'),
    'This application is not a supported Lever target.',
  )
  assert.equal(
    supervisedBlockerLabel('unsupported_platform', null),
    'This application is not a registered supervised-submission target.',
  )
})

test('hashes are shortened for display without losing both identifying ends', () => {
  const value = 'a'.repeat(32) + 'b'.repeat(32)
  assert.equal(shortHash(value), `${'a'.repeat(12)}…${'b'.repeat(8)}`)
  assert.equal(shortHash('abc'), 'abc')
  assert.equal(shortHash(''), 'Unavailable')
})

test('Lever identity extraction reads exact target and verification fields', () => {
  assert.deepEqual(
    readLeverTargetIdentity({
      application_url: 'https://jobs.lever.co/acme/posting/apply',
      adapter_version: '1.1.0',
      target_identity_hash: 't'.repeat(64),
      target_identity_verified: true,
      target_identity: {
        site: 'acme',
        posting_id: 'posting',
        region: 'global',
        canonical_apply_url: 'https://jobs.lever.co/acme/posting/apply',
        posting_metadata_hash: 'm'.repeat(64),
      },
    }),
    {
      site: 'acme',
      postingId: 'posting',
      region: 'global',
      canonicalUrl: 'https://jobs.lever.co/acme/posting/apply',
      postingMetadataHash: 'm'.repeat(64),
      targetIdentityHash: 't'.repeat(64),
      adapterVersion: '1.1.0',
      verified: true,
    },
  )
})
