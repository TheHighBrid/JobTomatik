import assert from 'node:assert/strict'
import test from 'node:test'
import { handoffExpired, handoffPointer, handoffReadErrorMessage, retryableHandoffRead } from '../src/utils/handoffViewport.js'

test('only transient read failures recover automatically; owner actions remain separate', () => {
  for (const error of [{ request: {}, code: 'ECONNABORTED' }, { response: { status: 503 } }, { response: { status: 429 } }]) {
    assert.equal(retryableHandoffRead(error), true)
    assert.match(handoffReadErrorMessage(error, 'fallback'), /Reconnecting automatically/)
  }
  for (const status of [401, 403, 409, 410, 422]) {
    assert.equal(retryableHandoffRead({ response: { status } }), false)
    assert.equal(handoffReadErrorMessage({ response: { status } }, 'Preserve the retained outcome'), 'Preserve the retained outcome')
  }
})

test('owner taps map to screenshot pixels after mobile scaling', () => {
  const image = { naturalWidth: 1280, naturalHeight: 900, getBoundingClientRect: () => ({ left: 20, top: 100, width: 320, height: 225 }) }
  assert.deepEqual(handoffPointer(image, 180, 212.5), { x: 640, y: 450 })
  assert.equal(handoffPointer(image, 19, 212.5), null)
  assert.equal(handoffPointer(image, 340, 212.5), null)
  assert.equal(handoffPointer({ ...image, naturalWidth: 0 }, 180, 212.5), null)
})

test('aware and SQLite UTC expiry both disable interaction at the deadline', () => {
  const now = Date.parse('2026-10-15T17:00:00Z')
  for (const value of ['2026-10-15T17:00:00', '2026-10-15T17:00:00+00:00', '2026-10-15T13:00:00-04:00']) assert.equal(handoffExpired({ expires_at: value }, now), true)
  assert.equal(handoffExpired({ expires_at: '2026-10-15T17:00:01Z' }, now), false)
  assert.equal(handoffExpired({ expires_at: 'invalid' }, now), true)
})
