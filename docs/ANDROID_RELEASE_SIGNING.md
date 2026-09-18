# Android release signing

JobTomatik's Android client has two separate signing modes:

- **development signing** for local/debug and prepublication builds;
- **persistent release signing** for production installable updates.

The repository never stores the release keystore, private key, certificate password, or key password.

## Required protected secrets

Before running the production-signed build, configure these secrets for the protected `android-production-release` environment or repository:

```text
JOBTOMATIK_KEYSTORE_BASE64
JOBTOMATIK_KEYSTORE_PASSWORD
JOBTOMATIK_KEY_ALIAS
JOBTOMATIK_KEY_PASSWORD
JOBTOMATIK_RELEASE_CERT_SHA256
```

`JOBTOMATIK_RELEASE_CERT_SHA256` is the SHA-256 fingerprint of the persistent release certificate normalized to 64 hexadecimal characters.

The workflow never writes keystore passwords or the key password to `GITHUB_ENV`. The base64 keystore exists only long enough to decode an ephemeral runner file. Passwords and aliases are scoped directly to the signing step, and certificate verification receives only the expected public fingerprint.

## Production build contract

`.github/workflows/android-production-release.yml` is an owner-only manual build with **no workflow inputs**. The build identity is derived from the checked-out current `main` tree:

- exact source commit = current `origin/main`;
- versionName and versionCode = `frontend/android/app/build.gradle`;
- intended release tag = `v<versionName>`.

Removing user-controlled workflow inputs keeps the build output bound to reviewed source rather than typed parameters.

The workflow refuses to build when:

- current source is not exactly `origin/main`;
- versionName is not semantic `major.minor.patch`;
- versionCode is not greater than the development-signed v2.1.0 baseline `210`;
- versionCode is not greater than every versionCode retained in existing `v*` tags;
- the intended `v<versionName>` tag already exists;
- any mandatory signing secret is missing;
- the keystore/alias cannot be opened;
- the produced APK identity does not match the source version;
- the produced APK certificate does not match `JOBTOMATIK_RELEASE_CERT_SHA256`.

The workflow is **build-only**. It has read-only repository permissions and does not create a release or tag.

## Gradle fail-closed behavior

Release artifact-producing Gradle tasks such as `assembleRelease` and `bundleRelease` require the persistent signing material. Diagnostic release tasks such as `lintRelease` remain usable without the production keystore.

There is no silent fallback from a production release artifact build to debug signing.

## One-time migration from development-signed v2.1.0

The existing v2.1.0 Android client was development-signed. Android will not accept a differently signed APK as an in-place update of that installed package.

For the first persistent-release-signed client:

1. finish or safely pause any active supervised application/handoff;
2. preserve the Termux/Ubuntu backend database, files, runtime state, and résumé data;
3. retain any user-managed client settings that are not stored in the backend;
4. remove the development-signed Android client only after active browser/application work is safe;
5. install the first APK signed by the persistent production certificate;
6. reconnect it to the existing local backend;
7. verify backend data and application state before resuming work.

Do **not** perform this migration during an active supervised submission or retained-browser handoff.

After that one-time boundary, subsequent APKs signed with the same certificate can use Android's normal in-place update path, subject to package/version rules.

## Evidence retained per production build

A successful build artifact contains:

- the production-signed APK;
- APK SHA-256 checksum;
- `APK-BADGING.txt`;
- `APK-SIGNING.txt`;
- `SOURCE-COMMIT.txt`;
- `BUILD-INFO.txt` with source, version, signing mode, certificate fingerprint, and previous tagged versionCode maximum.

These artifacts prove what was built and signed. They do not authorize publication, ATS submission, adapter promotion, or autonomous operation.
