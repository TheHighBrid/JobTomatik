import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const control = readFileSync(
  new URL('../src/components/CurrentLeverRuntimeControl.jsx', import.meta.url),
  'utf8',
)

test('runtime maintenance is available in-app without terminal commands', () => {
  assert.equal(control.includes("'/controller/android-runtime/update'"), true)
  assert.equal(control.includes('Update Android runtime'), true)
  assert.equal(control.includes('Update runtime'), true)
  assert.equal(control.includes('Confirm runtime update'), true)
  assert.equal(control.includes('jobtomatik update'), false)
  assert.equal(control.includes('proot-distro'), false)
})

test('runtime update is a two-step fail-safe action', () => {
  assert.equal(control.includes('const [confirmingUpdate, setConfirmingUpdate]'), true)
  assert.equal(control.includes('{!leaseActive && ('), true)
  assert.equal(
    control.includes('disabled={!available || transitionPending || updateMutation.isPending}'),
    true,
  )
  assert.equal(
    control.includes('No application approval or submit action is created.'),
    true,
  )
})

test('runtime update expects local restart and reconnect instead of replay', () => {
  assert.equal(control.includes('JobTomatik will reconnect automatically after the verified restart.'), true)
  assert.equal(control.includes('refetchInterval: 2500'), true)
  assert.equal(control.includes('no control request is replayed automatically'), true)
  assert.equal(control.includes('uncertain_no_replay'), true)
})
