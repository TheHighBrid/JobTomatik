import assert from 'node:assert/strict'
import test from 'node:test'

import { isLocalApiHostname, normalizeApiBaseUrl } from '../src/api/url.js'
import { readStoredJson, safeLocalStorage } from '../src/storage.js'

test('API URL normalization keeps local development on HTTP', () => {
  assert.equal(normalizeApiBaseUrl('127.0.0.1:8010'), 'http://127.0.0.1:8010')
  assert.equal(normalizeApiBaseUrl('192.168.1.25:8010/api/'), 'http://192.168.1.25:8010')
  assert.equal(normalizeApiBaseUrl('jobtomatik.local:8010'), 'http://jobtomatik.local:8010')
})

test('API URL normalization upgrades public hosts and strips a duplicated API suffix', () => {
  assert.equal(normalizeApiBaseUrl('api.example.com'), 'https://api.example.com')
  assert.equal(normalizeApiBaseUrl('https://api.example.com/api/'), 'https://api.example.com')
})

test('API URL normalization rejects unsafe remote HTTP and embedded secrets', () => {
  assert.throws(
    () => normalizeApiBaseUrl('http://api.example.com'),
    /must use HTTPS/,
  )
  assert.throws(
    () => normalizeApiBaseUrl('https://user:secret@api.example.com'),
    /embedded credentials/,
  )
  assert.throws(
    () => normalizeApiBaseUrl('https://api.example.com?token=secret'),
    /query string or fragment/,
  )
})

test('local hostname detection covers Android emulator and private networks', () => {
  assert.equal(isLocalApiHostname('10.0.2.2'), true)
  assert.equal(isLocalApiHostname('172.20.4.8'), true)
  assert.equal(isLocalApiHostname('8.8.8.8'), false)
})

test('corrupt stored JSON is removed instead of crashing application startup', () => {
  const values = new Map([['user', '{broken-json']])
  globalThis.window = {
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
  }

  assert.equal(readStoredJson('user'), null)
  assert.equal(values.has('user'), false)

  safeLocalStorage.setItem('token', 'abc')
  assert.equal(safeLocalStorage.getItem('token'), 'abc')
  safeLocalStorage.removeItem('token')
  assert.equal(safeLocalStorage.getItem('token'), null)

  delete globalThis.window
})
