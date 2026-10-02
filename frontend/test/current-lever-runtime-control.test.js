import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const control = readFileSync(
  new URL('../src/components/CurrentLeverRuntimeControl.jsx', import.meta.url),
  'utf8',
)
const page = readFileSync(
  new URL('../src/pages/CurrentLeverOperator.jsx', import.meta.url),
  'utf8',
)

test('Current Lever workspace exposes native runtime control without terminal commands', () => {
  assert.equal(page.includes('CurrentLeverRuntimeControl'), true)
  assert.equal(control.includes("api.get('/supervised-pilot/current-lever/runtime-control')"), true)
  assert.equal(control.includes('/runtime-control/arm`'), true)
  assert.equal(control.includes("api.post(\n      '/supervised-pilot/current-lever/runtime-control/disarm'"), true)
  assert.equal(control.includes('jobtomatik-pilot arm'), false)
  assert.equal(control.includes('proot-distro'), false)
})

test('runtime arm is explicit and bound to the selected application', () => {
  assert.equal(
    control.includes('acknowledgment: `ENABLE LEVER SUPERVISED WINDOW ${applicationId}`'),
    true,
  )
  assert.equal(control.includes('Confirm supervised window'), true)
  assert.equal(control.includes('Enable supervised runtime window'), true)
  assert.equal(control.includes("candidate.automation_state === 'ready_to_apply'"), true)
})

test('runtime control never becomes submission approval UI', () => {
  assert.equal(control.includes('/approvals'), false)
  assert.equal(control.includes('/submit'), false)
  assert.equal(control.includes('queueSupervisedSubmission'), false)
  assert.equal(control.includes('does not approve an application, queue a submission'), true)
  assert.equal(control.includes('Final submission still requires the separate exact application approval'), true)
})

test('native restart is treated as reconnecting state, never as automatic replay', () => {
  assert.equal(control.includes('refetchInterval: 2500'), true)
  assert.equal(control.includes('failureCount < 2'), true)
  assert.equal(control.includes('isMissingRuntimeControlEndpoint(error)'), true)
  assert.equal(control.includes('no control request is replayed automatically'), true)
  assert.equal(control.includes('uncertain_no_replay'), true)
  assert.equal(control.includes('The process-bound lease state shown here is authoritative.'), true)
})

test('active lease restore is restricted to the signed lease owner account', () => {
  assert.equal(control.includes('const canDisarm = runtime?.can_disarm === true'), true)
  assert.equal(control.includes('Restore fail-safe runtime'), true)
  assert.equal(control.includes("'/supervised-pilot/current-lever/runtime-control/disarm'"), true)
  assert.equal(control.includes('disabled={!canDisarm || !controllerReady'), true)
  assert.equal(
    control.includes('cannot revoke another account&apos;s active supervised window'),
    true,
  )
})
