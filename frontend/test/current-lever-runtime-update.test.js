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

test('native bootstrap repairs a current Android runtime whose security signer is unavailable', () => {
  assert.equal(control.includes('const runtimeNeedsNativeRepair = ('), true)
  assert.equal(control.includes('runtime?.android_managed_api === true'), true)
  assert.equal(control.includes('&& controllerReady'), true)
  assert.equal(control.includes('&& !available'), true)
  assert.equal(control.includes('if (runtimeNeedsNativeRepair)'), true)
  assert.equal(control.includes("mode: 'native-security-repair'"), true)
  assert.equal(control.includes('Runtime security migration required.'), true)
  assert.equal(control.includes('Repair runtime security'), true)
  assert.equal(control.includes('existing Answer Vault and handoff encryption key'), true)
})

test('offline native controller uses safe native bootstrap instead of a doomed server request', () => {
  const offlineBootstrap = control.indexOf('if (nativeBootstrapSafe && !controllerReady)')
  const serverPost = control.indexOf("'/controller/android-runtime/update'")
  assert.equal(offlineBootstrap >= 0 && offlineBootstrap < serverPost, true)
  assert.equal(control.includes("return { mode: 'native-bootstrap', result }"), true)
})

test('current healthy runtime still uses the signed server update path and does not bypass safety errors', () => {
  const nativeRepair = control.indexOf('if (runtimeNeedsNativeRepair)')
  const serverPost = control.indexOf("'/controller/android-runtime/update'")
  const nonMissingFailure = control.indexOf('if (!endpointMissing)')
  assert.equal(nativeRepair >= 0 && nativeRepair < serverPost, true)
  assert.equal(serverPost >= 0 && serverPost < nonMissingFailure, true)
  assert.equal(control.includes('throw error'), true)
})

test('missing runtime-control endpoint stops retrying and unlocks legacy bootstrap safely', () => {
  assert.equal(control.includes('const endpointMissing = status === 404 || status === 405'), true)
  assert.equal(control.includes('if (!endpointMissing)'), true)
  assert.equal(control.includes('if (!nativeBootstrapSafe && !legacyNativeBootstrapSafe)'), true)
  assert.equal(control.includes('updateRuntimeViaLegacyNativeBootstrap()'), true)
  assert.equal(control.includes('updateRuntimeViaNativeBootstrap()'), true)
  assert.equal(control.includes("mode: 'legacy-native-bootstrap'"), true)
  assert.equal(control.includes("mode: 'native-bootstrap'"), true)
  assert.equal(control.includes('isMissingRuntimeControlEndpoint(error)'), true)
  assert.equal(
    control.includes('!isMissingRuntimeControlEndpoint(error) && failureCount < 2'),
    true,
  )
  assert.equal(control.includes('runtimeEndpointMissing'), true)
  assert.equal(control.includes('legacyNativeBootstrapSafe'), true)
  assert.equal(control.includes('workspaceQuery.isSuccess'), true)
  assert.equal(control.includes('executingSubmissionCount === 0'), true)
  assert.equal(control.includes('Legacy Android runtime detected.'), true)
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

test('runtime security migration tolerates the expected one-time reauthentication boundary', () => {
  assert.equal(control.includes('JWT signing secret'), true)
  assert.equal(control.includes('Sign in again if prompted'), true)
  assert.equal(control.includes('existing encrypted application answers were preserved'), true)
})

test('runtime update expects local restart and reconnect instead of replay', () => {
  assert.equal(control.includes('JobTomatik will reconnect automatically after the verified restart.'), true)
  assert.equal(control.includes('refetchInterval: 2500'), true)
  assert.equal(control.includes('no control request is replayed automatically'), true)
  assert.equal(control.includes('uncertain_no_replay'), true)
})
