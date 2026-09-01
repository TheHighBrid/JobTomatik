import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const plugin = readFileSync(
  new URL('../android/app/src/main/java/ca/jobtomatik/app/NativeRuntimeBootstrapPlugin.java', import.meta.url),
  'utf8',
)
const activity = readFileSync(
  new URL('../android/app/src/main/java/ca/jobtomatik/app/MainActivity.java', import.meta.url),
  'utf8',
)
const manifest = readFileSync(
  new URL('../android/app/src/main/AndroidManifest.xml', import.meta.url),
  'utf8',
)
const client = readFileSync(
  new URL('../src/native/runtimeBootstrap.js', import.meta.url),
  'utf8',
)

test('native bootstrap is registered and permission scoped to Termux RUN_COMMAND', () => {
  assert.equal(activity.includes('registerPlugin(NativeRuntimeBootstrapPlugin.class)'), true)
  assert.equal(manifest.includes('com.termux.permission.RUN_COMMAND'), true)
  assert.equal(manifest.includes('<package android:name="com.termux" />'), true)
  assert.equal(plugin.includes('@Permission('), true)
  assert.equal(plugin.includes('TERMUX_PERMISSION_ALIAS'), true)
})

test('native bootstrap availability trusts the registered plugin after local runtime refresh', () => {
  assert.equal(client.includes("Capacitor.isPluginAvailable('NativeRuntimeBootstrap')"), true)
  assert.equal(client.includes('Capacitor.isNativePlatform()'), false)
  assert.equal(client.includes("Capacitor.getPlatform() === 'android'"), false)
})

test('native bootstrap exposes only fixed JobTomatik maintenance executables', () => {
  assert.equal(
    plugin.includes('private static final String TERMUX_BIN = "/data/data/com.termux/files/usr/bin/"'),
    true,
  )
  assert.equal(plugin.includes('TERMUX_BIN + "jobtomatik"'), true)
  assert.equal(plugin.includes('TERMUX_BIN + "jobtomatik-pilot-controller-manager"'), true)
  assert.equal(plugin.includes('TERMUX_BIN + "proot-distro"'), true)
  assert.equal(plugin.includes('new String[] { "update" }'), true)
  assert.equal(plugin.includes('new String[] { "stop" }'), true)
  assert.equal(plugin.includes('new String[] { "start" }'), true)
  assert.equal(plugin.includes('call.getString('), false)
  assert.equal(plugin.includes('call.getArray('), false)
  assert.equal(plugin.includes('call.getObject('), false)
  assert.equal(plugin.includes('TERMUX_EXTRA_RUNNER, "app-shell"'), true)
})

test('global bootstrap guard is fixed, shell-free, and covers every platform', () => {
  assert.equal(plugin.includes('GLOBAL_EXECUTION_GUARD_CODE'), true)
  assert.equal(plugin.includes('SubmissionAttemptStatus.queued.value'), true)
  assert.equal(plugin.includes('SubmissionAttemptStatus.in_progress.value'), true)
  assert.equal(plugin.includes('JOBTOMATIK_BOOTSTRAP_EXECUTING_ATTEMPTS=%d'), true)
  assert.equal(plugin.includes('raise SystemExit(0 if count == 0 else 42)'), true)
  assert.equal(plugin.includes('"login",'), true)
  assert.equal(plugin.includes('"ubuntu",'), true)
  assert.equal(plugin.includes('BACKEND_PYTHON'), true)
  assert.equal(plugin.includes('"-c",'), true)
  assert.equal(plugin.includes('"bash"'), false)
  assert.equal(plugin.includes('"-lc"'), false)
})

test('native bootstrap waits for the trusted Termux result and honors Android RESULT_OK', () => {
  assert.equal(plugin.includes('com.termux.RUN_COMMAND_PENDING_INTENT'), true)
  assert.equal(plugin.includes('PendingIntent.FLAG_MUTABLE'), true)
  assert.equal(plugin.includes('intent.getBundleExtra(TERMUX_RESULT_BUNDLE)'), true)
  assert.equal(plugin.includes('result.getInt(TERMUX_RESULT_ERR, Integer.MIN_VALUE)'), true)
  assert.equal(plugin.includes('if (err != android.app.Activity.RESULT_OK)'), true)
  assert.equal(plugin.includes('if (err != 0)'), false)
  assert.equal(plugin.includes('if (exitCode != 0)'), true)
  assert.equal(plugin.includes('response.put("completed", true)'), true)
})

test('bootstrap quiesces controller and rechecks backend state before update', () => {
  assert.equal(client.includes('NativeRuntimeBootstrap.quiesceController()'), true)
  assert.equal(client.includes('controller_available === false'), true)
  assert.equal(client.includes("api.get('/supervised-pilot/current-lever/runtime-control')"), true)
  assert.equal(client.includes("api.get('/supervised-pilot/current-lever')"), true)
  assert.equal(client.includes('Boolean(lastRuntime?.pending_request)'), true)
  assert.equal(client.includes('Boolean(lastRuntime?.inflight_request)'), true)
  assert.equal(client.includes('active - uncertain'), true)
  assert.equal(client.includes('await assertNoExecutingSubmissionsGlobally()'), true)
  assert.equal(client.includes('await NativeRuntimeBootstrap.updateRuntime()'), true)
})

test('legacy bootstrap skips nonexistent controller but still runs the global durable guard', () => {
  assert.equal(client.includes('updateRuntimeViaLegacyNativeBootstrap'), true)
  const legacyStart = client.indexOf('export async function updateRuntimeViaLegacyNativeBootstrap')
  const normalStart = client.indexOf('export async function updateRuntimeViaNativeBootstrap')
  const legacyBlock = client.slice(legacyStart, normalStart)
  assert.equal(legacyBlock.includes('await assertNoExecutingSubmissionsGlobally()'), true)
  assert.equal(legacyBlock.includes('NativeRuntimeBootstrap.updateRuntime()'), true)
  assert.equal(legacyBlock.includes('quiesceController'), false)
  assert.equal(legacyBlock.includes('restoreController'), false)
})

test('bootstrap restores native controller whenever quiesced safety, global guard, or update aborts', () => {
  assert.equal(client.includes('let controllerQuiesced = false'), true)
  assert.equal(client.includes('await restoreNativeRuntimeController()'), true)
  assert.equal(client.includes('Pilot controller restore also failed'), true)
})

test('javascript exposes no arbitrary command or argument surface', () => {
  assert.equal(client.includes("registerPlugin('NativeRuntimeBootstrap')"), true)
  assert.equal(client.includes('NativeRuntimeBootstrap.updateRuntime()'), true)
  assert.equal(client.includes('NativeRuntimeBootstrap.quiesceController()'), true)
  assert.equal(client.includes('NativeRuntimeBootstrap.assertNoExecutingSubmissions()'), true)
  assert.equal(client.includes('NativeRuntimeBootstrap.restoreController()'), true)
  assert.equal(client.includes('command:'), false)
  assert.equal(client.includes('arguments:'), false)
})
