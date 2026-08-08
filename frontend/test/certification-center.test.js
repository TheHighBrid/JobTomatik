import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(
  new URL('../src/pages/CertificationCenter.jsx', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../src/api/certification.js', import.meta.url),
  'utf8',
)
const appSource = readFileSync(
  new URL('../src/App.jsx', import.meta.url),
  'utf8',
)
const layoutSource = readFileSync(
  new URL('../src/components/Layout.jsx', import.meta.url),
  'utf8',
)

test('certification center preserves evidence review authorization and execution separation', () => {
  for (const phrase of [
    'Evidence, review, authorization, and execution are separate gates.',
    'Nothing on this page silently enables real submission.',
    'Recording evidence does not certify it and never enables submission.',
    'Verification still does not enable submission.',
    'It does not enable real submission or autopilot.',
    'Separate runtime gate:',
  ]) {
    assert.equal(pageSource.includes(phrase), true, `missing certification safety copy: ${phrase}`)
  }
})

test('certification UI requires typed exact verification and authorization phrases', () => {
  assert.equal(pageSource.includes('VERIFY EVIDENCE ${verifyTarget.evidence_id} ${shortSha(verifyTarget.commit_sha)}'), true)
  assert.equal(pageSource.includes('AUTHORIZE ${scope.toUpperCase()} ${manifest.release_version} ${shortSha(manifest.candidate_revision)}'), true)
  assert.equal(pageSource.includes('REVOKE AUTHORIZATION ${authorization.authorization_id}'), true)
  assert.equal(pageSource.includes('verifyAck !== expectedAck'), true)
  assert.equal(pageSource.includes('ack !== expected'), true)
  assert.equal(pageSource.includes('revokeAck !== revokeExpected'), true)
})

test('certification API keeps record review authorize and revoke as separate calls', () => {
  assert.equal(apiSource.includes("api.post('/certification/evidence', data)"), true)
  assert.equal(apiSource.includes('/verify`'), true)
  assert.equal(apiSource.includes("api.post('/certification/authorizations', data)"), true)
  assert.equal(apiSource.includes('/revoke`'), true)
  assert.equal(apiSource.includes("api.get('/certification/manifest'"), true)
})

test('certification center is routed and visible in primary navigation', () => {
  assert.equal(appSource.includes('CertificationCenter'), true)
  assert.equal(appSource.includes('path="certification"'), true)
  assert.equal(layoutSource.includes("to: '/certification'"), true)
  assert.equal(layoutSource.includes("label: 'Certification Center'"), true)
})

test('shadow evidence creation is routed to the full-stack campaign surface', () => {
  for (const evidenceType of ['shadow_run_4h', 'shadow_run_8h', 'shadow_run_24h']) {
    assert.equal(pageSource.includes(`'${evidenceType}'`), false, `${evidenceType} must not be manually selectable`)
  }
  assert.equal(pageSource.includes('Shadow evidence has a dedicated provenance path.'), true)
  assert.equal(pageSource.includes('4h, 8h, and 24h shadow records cannot be entered here.'), true)
  assert.equal(pageSource.includes('href="/shadow-campaigns"'), true)
  assert.equal(pageSource.includes('revalidates its linked full-stack campaign before and after review'), true)
  assert.equal(pageSource.includes('unlinked shadow evidence fails closed'), true)
})

test('manual evidence form retains optional measured duration for non-shadow evidence', () => {
  assert.equal(pageSource.includes('Measured duration seconds'), true)
  assert.equal(pageSource.includes('Optional when this evidence type has a measured duration'), true)
  assert.equal(pageSource.includes('qualification_eligible'), false)
})
