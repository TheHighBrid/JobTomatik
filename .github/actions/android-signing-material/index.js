const fs = require('fs');
const path = require('path');

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
if (!runnerTemp) {
  throw new Error('RUNNER_TEMP is unavailable');
}

const dir = path.join(runnerTemp, 'jobtomatik-signing');
fs.mkdirSync(dir, { recursive: true, mode: 0o700 });

const files = {
  'release.jks': decodedKeystore,
  'store-password': Buffer.from(storePassword, 'utf8'),
  'key-alias': Buffer.from(keyAlias, 'utf8'),
  'key-password': Buffer.from(keyPassword, 'utf8'),
};

for (const [name, content] of Object.entries(files)) {
  fs.writeFileSync(path.join(dir, name), content, { mode: 0o600 });
}

process.stdout.write('Android signing material prepared in ephemeral runner storage.\n');
