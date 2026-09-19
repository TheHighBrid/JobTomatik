const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function requiredInput(name) {
  const key = 'INPUT_' + name.toUpperCase();
  const value = process.env[key] || '';
  if (!value) throw new Error('Missing required signing input');
  return value;
}

function requiredLine(value, index) {
  if (typeof value !== 'string' || !value || /\r|\n/.test(value)) {
    throw new Error('Signing material item ' + index + ' is missing or invalid');
  }
  return value;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(command + ' exited with status ' + result.status);
  }
}

const encodedBundle = requiredInput('SIGNING_BUNDLE_BASE64').replace(/\s+/g, '');
// Do not leave the opaque GitHub Actions input available to child processes.
delete process.env.INPUT_SIGNING_BUNDLE_BASE64;

if (!/^[A-Za-z0-9+/]+={0,2}$/.test(encodedBundle)) {
  throw new Error('Signing bundle is not valid base64 text');
}

let material;
try {
  material = JSON.parse(Buffer.from(encodedBundle, 'base64').toString('utf8'));
} catch {
  throw new Error('Signing bundle does not decode to valid JSON');
}
if (!Array.isArray(material) || material.length !== 4) {
  throw new Error('Signing bundle must contain exactly four ordered items');
}

const item0 = requiredLine(material[0], 0).replace(/\s+/g, '');
const item1 = requiredLine(material[1], 1);
const item2 = requiredLine(material[2], 2);
const item3 = requiredLine(material[3], 3);

if (!/^[A-Za-z0-9+/]+={0,2}$/.test(item0)) {
  throw new Error('Signing material item 0 is not valid base64 text');
}
const identityBytes = Buffer.from(item0, 'base64');
if (!identityBytes.length) throw new Error('Decoded signing identity is empty');

const runnerTemp = process.env.RUNNER_TEMP;
const workspace = process.env.GITHUB_WORKSPACE;
if (!runnerTemp || !workspace) throw new Error('Runner workspace paths are unavailable');

const dir = path.join(runnerTemp, 'jobtomatik-signing');
const identityPath = path.join(dir, 'identity.jks');
const item1Path = path.join(dir, 'material-1');

const childEnv = {};
for (const name of [
  'PATH',
  'HOME',
  'JAVA_HOME',
  'ANDROID_HOME',
  'ANDROID_SDK_ROOT',
  'GRADLE_USER_HOME',
  'RUNNER_TEMP',
  'TMPDIR',
  'TEMP',
  'TMP',
  'LANG',
  'LC_ALL',
  'CI',
]) {
  if (process.env[name]) childEnv[name] = process.env[name];
}

fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
fs.writeFileSync(identityPath, identityBytes, { mode: 0o600 });
fs.writeFileSync(item1Path, item1, { mode: 0o600 });
fs.writeFileSync(path.join(dir, 'material-2'), item2, { mode: 0o600 });
fs.writeFileSync(path.join(dir, 'material-3'), item3, { mode: 0o600 });

try {
  run('keytool', [
    '-list',
    '-keystore',
    identityPath,
    '-storepass:file',
    item1Path,
    '-alias',
    item2,
  ], { env: childEnv });

  const androidDir = path.join(workspace, 'frontend', 'android');
  const gradlew = path.join(androidDir, 'gradlew');
  fs.chmodSync(gradlew, 0o755);

  const gradleEnv = { ...childEnv, JOBTOMATIK_SIGNING_DIR: dir };
  run(gradlew, ['--no-daemon', 'lintRelease', 'assembleRelease'], {
    cwd: androidDir,
    env: gradleEnv,
  });

  process.stdout.write('Production Android release APK assembled with protected signing material.\n');
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}
