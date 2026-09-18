const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function requiredInput(name) {
  const key = 'INPUT_' + name.toUpperCase();
  const value = process.env[key] || '';
  if (!value) {
    throw new Error('Missing required signing input: ' + name);
  }
  return value;
}

function requiredText(bundle, key) {
  const value = bundle[key];
  if (typeof value !== 'string' || !value || /\r|\n/.test(value)) {
    throw new Error('Signing bundle field is missing or invalid: ' + key);
  }
  return value;
}

function mask(value) {
  process.stdout.write('::add-mask::' + value + '\n');
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    ...options,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(command + ' exited with status ' + result.status);
  }
}

const bundleText = requiredInput('SIGNING_BUNDLE_BASE64').replace(/\s+/g, '');
if (!/^[A-Za-z0-9+/]+={0,2}$/.test(bundleText)) {
  throw new Error('Signing bundle is not valid base64 text');
}

let bundle;
try {
  bundle = JSON.parse(Buffer.from(bundleText, 'base64').toString('utf8'));
} catch (error) {
  throw new Error('Signing bundle does not decode to valid JSON');
}
if (!bundle || typeof bundle !== 'object' || Array.isArray(bundle)) {
  throw new Error('Signing bundle JSON must be an object');
}

const keystoreBase64 = requiredText(bundle, 'keystore_base64').replace(/\s+/g, '');
const storePassword = requiredText(bundle, 'keystore_password');
const keyAlias = requiredText(bundle, 'key_alias');
const keyPassword = requiredText(bundle, 'key_password');

if (!/^[A-Za-z0-9+/]+={0,2}$/.test(keystoreBase64)) {
  throw new Error('Bundled keystore is not valid base64 text');
}
const decodedKeystore = Buffer.from(keystoreBase64, 'base64');
if (!decodedKeystore.length) {
  throw new Error('Decoded keystore is empty');
}

for (const value of [
  bundleText,
  keystoreBase64,
  storePassword,
  keyAlias,
  keyPassword,
]) {
  mask(value);
}

const runnerTemp = process.env.RUNNER_TEMP;
const workspace = process.env.GITHUB_WORKSPACE;
if (!runnerTemp || !workspace) {
  throw new Error('Runner workspace paths are unavailable');
}

const dir = path.join(runnerTemp, 'jobtomatik-signing');
const keystorePath = path.join(dir, 'release.jks');
const storePasswordPath = path.join(dir, 'store-password');
const keyAliasPath = path.join(dir, 'key-alias');
const keyPasswordPath = path.join(dir, 'key-password');

fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
fs.writeFileSync(keystorePath, decodedKeystore, { mode: 0o600 });
fs.writeFileSync(storePasswordPath, storePassword, { mode: 0o600 });
fs.writeFileSync(keyAliasPath, keyAlias, { mode: 0o600 });
fs.writeFileSync(keyPasswordPath, keyPassword, { mode: 0o600 });

try {
  run('keytool', [
    '-list',
    '-keystore',
    keystorePath,
    '-storepass:file',
    storePasswordPath,
    '-alias',
    keyAlias,
  ]);

  const androidDir = path.join(workspace, 'frontend', 'android');
  const gradlew = path.join(androidDir, 'gradlew');
  fs.chmodSync(gradlew, 0o755);

  run(gradlew, ['--no-daemon', 'lintRelease', 'assembleRelease'], {
    cwd: androidDir,
    env: {
      ...process.env,
      JOBTOMATIK_KEYSTORE_PATH: keystorePath,
      JOBTOMATIK_KEYSTORE_PASSWORD: storePassword,
      JOBTOMATIK_KEY_ALIAS: keyAlias,
      JOBTOMATIK_KEY_PASSWORD: keyPassword,
    },
  });

  process.stdout.write('Production Android release APK assembled with protected signing material.\n');
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}
