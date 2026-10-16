import assert from 'node:assert/strict'
import test from 'node:test'
import { QueryClient, QueryObserver } from '@tanstack/react-query'
import { jt5PollingInterval } from '../src/jt5StatusPolling.js'

test('polling reads the raw query response even when select exposes the payload', async () => {
  const client = new QueryClient()
  const payload = { latest_attempt: { status: 'queued', dispatch_status: 'published' } }
  const observer = new QueryObserver(client, {
    queryKey: ['jt5-status'],
    queryFn: async () => ({ data: payload, status: 200 }),
    select: (response) => response.data,
    refetchInterval: (query) => jt5PollingInterval(query.state.data),
  })
  try {
    await observer.refetch()
    assert.deepEqual(observer.getCurrentResult().data, payload)
    const query = client.getQueryCache().find({ queryKey: ['jt5-status'] })
    assert.equal(query.state.data.latest_attempt, undefined)
    assert.equal(query.options.refetchInterval(query), 1500)
    client.setQueryData(['jt5-status'], {
      data: { latest_attempt: { status: 'succeeded', dispatch_status: 'worker_completed' } },
    })
    assert.equal(query.options.refetchInterval(query), false)
  } finally {
    observer.destroy()
    client.clear()
  }
})

for (const status of ['queued', 'in_progress']) {
  test(`continues read-only polling for a ${status} attempt`, () => {
    const payload = { latest_attempt: { status, dispatch_status: 'published' } }
    assert.equal(jt5PollingInterval(payload), 1500)
    assert.equal(jt5PollingInterval({ data: payload }), 1500)
  })
}

for (const status of ['succeeded', 'failed', 'uncertain']) {
  test(`stops polling for a ${status} outcome`, () => {
    assert.equal(jt5PollingInterval({ data: { latest_attempt: { status } } }), false)
  })
}

test('does not continue a publication requiring reconciliation', () => {
  assert.equal(jt5PollingInterval({ data: {
    latest_attempt: { status: 'queued', dispatch_status: 'reconciliation_required' },
  } }), false)
})

test('missing status or attempt never starts a polling loop', () => {
  for (const response of [undefined, null, {}, { data: { latest_attempt: null } }]) {
    assert.equal(jt5PollingInterval(response), false)
  }
})
