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
    control.includes('disabled={!updateControlAvailable || transitionPending || updateMutation.isPending}'),
    true,
  )
  assert.equal(
    control.includes('No application approval or submit action is created.'),
    true,
  )
})

test('native bootstrap is only an old-backend compatibility ladder', () => {
  assert.equal(control.includes('const endpointMissing = status === 404 || status === 405'), true)
  assert.equal(control.includes('if (!endpointMissing)'), true)
  assert.equal(control.includes('if (!nativeBootstrapSafe && !legacyNativeBootstrapSafe)'), true)
  assert.equal(control.includes('updateRuntimeViaLegacyNativeBootstrap()'), true)
  assert.equal(control.includes('updateRuntimeViaNativeBootstrap()'), true)
  assert.equal(control.includes("mode: 'legacy-native-bootstrap'"), true)
  assert.equal(control.includes("mode: 'native-bootstrap'"), true)
})

test('missing runtime-control endpoint stops retrying and unlocks legacy bootstrap safely', () => {
  assert.equal(control.includes('isMissingRuntimeControlEndpoint(error)'), true)
  assert.equal(
    control.includes('!isMissingRuntimeControlEndpoint(error) && failureCount < 2'),
    true,
  )
  assert.equal(control.includes('runtimeEndpointMissing'), true)
  assert.equal(control.includes('legacyNativeBootstrapSafe'), true)
  assert.equal(control.includes('workspaceQuery.isSuccess'), true)
  assert.equal(control.includes('executingSubmissionCount === 0'), true)
  assert.equal(
    control.includes('Legacy Android runtime detected.'),
    true,
  )
})

test('native bootstrap safety distinguishes execution from quarantined uncertainty', () => {
  assert.equal(control.includes('active - uncertain'), true)
  assert.equal(control.includes('executingSubmissionCount === 0'), true)
  assert.equal(control.includes('workspaceQuery.isSuccess'), true)
  assert.equal(control.includes('runtimeQuery.isSuccess'), true)
  assert.equal(control.includes('&& !leaseActive'), true)
})

test('runtime maintenance does not reinterpret quarantined uncertainty as execution', () => {
  assert.equal(
    control.includes('queued or in-progress submission is executing'),
    true,
  )
  assert.equal(
    control.includes('Quarantined uncertain applications remain immutable and are never retried'),
    true,
  )
})

test('runtime update expects local restart and reconnect instead of replay', () => {
  assert.equal(control.includes('JobTomatik will reconnect automatically after the verified restart.'), true)
  assert.equal(control.includes('refetchInterval: 2500'), true)
  assert.equal(control.includes('no control request is replayed automatically'), true)
  assert.equal(control.includes('uncertain_no_replay'), true)
})
