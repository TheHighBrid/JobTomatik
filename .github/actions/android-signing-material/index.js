const fs = require('fs');
const path = require('path');

function input(name) {
  const key = 'INPUT_' + name.toUpperCase();
  const value = process.env[key] || '';
  if (!value) {
    throw new Error('Missing required signing input: ' + name);
  }
  if (/\r|\n/.test(value) && name !== 'KEYSTORE_BASE64') {
    throw new Error('Signing text inputs must be single-line: ' + name);
  }
  return value;
}

function mask(value) {
  process.stdout.write('::add-mask::' + value + '\n');
}

const base64Raw = input('KEYSTORE_BASE64');
const storePassword = input('KEYSTORE_PASSWORD');
const keyAlias = input('KEY_ALIAS');
const keyPassword = input('KEY_PASSWORD');

const base64 = base64Raw.replace(/\s+/g, '');
if (!/^[A-Za-z0-9+/]+={0,2}$/.test(base64)) {
  throw new Error('Keystore input is not valid base64 text');
}

for (const value of [base64Raw, storePassword, keyAlias, keyPassword]) {
  mask(value);
}

const decoded = Buffer.from(base64, 'base64');
if (!decoded.length) {
  throw new Error('Decoded keystore is empty');
}

const runnerTemp = process.env.RUNNER_TEMP;
if (!runnerTemp) {
  throw new Error('RUNNER_TEMP is unavailable');
}

const dir = path.join(runnerTemp, 'jobtomatik-signing');
fs.mkdirSync(dir, { recursive: true, mode: 0o700 });

const files = {
  'release.jks': decoded,
  'store-password': Buffer.from(storePassword, 'utf8'),
  'key-alias': Buffer.from(keyAlias, 'utf8'),
  'key-password': Buffer.from(keyPassword, 'utf8'),
};

for (const [name, content] of Object.entries(files)) {
  fs.writeFileSync(path.join(dir, name), content, { mode: 0o600 });
}

process.stdout.write('Android signing material prepared in ephemeral runner storage.\n');
