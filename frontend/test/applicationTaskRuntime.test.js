import test from 'node:test'
import assert from 'node:assert/strict'

import {
  TASK_START_ACK_TIMEOUT_MS,
  applicationRuntimeBusy,
  isApplicationTaskTerminal,
  shouldReleaseUnacknowledgedTask,
} from '../src/applicationTaskRuntime.js'

test('terminal Celery states stop task polling', () => {
  assert.equal(isApplicationTaskTerminal('SUCCESS'), true)
  assert.equal(isApplicationTaskTerminal('FAILURE'), true)
  assert.equal(isApplicationTaskTerminal('REVOKED'), true)
  assert.equal(isApplicationTaskTerminal('PENDING'), false)
  assert.equal(isApplicationTaskTerminal('STARTED'), false)
})

test('an unacknowledged pending task is released after the dispatch timeout', () => {
  const queuedAt = 1_000
  assert.equal(shouldReleaseUnacknowledgedTask({
    taskStatus: 'PENDING',
    automationState: 'ready_to_apply',
    queuedAt,
    now: queuedAt + TASK_START_ACK_TIMEOUT_MS - 1,
  }), false)
  assert.equal(shouldReleaseUnacknowledgedTask({
    taskStatus: 'PENDING',
    automationState: 'ready_to_apply',
    queuedAt,
    now: queuedAt + TASK_START_ACK_TIMEOUT_MS,
  }), true)
})

test('a worker-owned applying attempt is never mistaken for a lost pending result', () => {
  assert.equal(shouldReleaseUnacknowledgedTask({
    taskStatus: 'PENDING',
    automationState: 'applying',
    queuedAt: 1_000,
    now: 1_000 + TASK_START_ACK_TIMEOUT_MS * 10,
  }), false)
})

test('runtime busy state survives a page reload through persisted application state', () => {
  assert.equal(applicationRuntimeBusy({
    submitting: false,
    taskId: '',
    automationState: 'applying',
  }), true)
  assert.equal(applicationRuntimeBusy({
    submitting: false,
    taskId: '',
    automationState: 'ready_to_apply',
  }), false)
})
