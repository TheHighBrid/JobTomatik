# Android release signing

JobTomatik's Android client has two distinct signing modes:

- **development signing** is for local/debug or prepublication builds;
- **persistent release signing** is required for production installable updates.

The repository never stores the release keystore, private key, or passwords.

## Required GitHub Actions secrets

Configure these secrets before running the production-signed workflow:

```text
JOBTOMATIK_KEYSTORE_BASE64
JOBTOMATIK_KEYSTORE_PASSWORD
JOBTOMATIK_KEY_ALIAS
JOBTOMATIK_KEY_PASSWORD
JOBTOMATIK_RELEASE_CERT_SHA256
```

`JOBTOMATIK_RELEASE_CERT_SHA256` is the SHA-256 fingerprint of the persistent release certificate, normalized to 64 hexadecimal characters. The workflow decodes the keystore only on the ephemeral runner, validates the key alias, signs the APK, and verifies the resulting APK certificate with `apksigner` before producing an artifact.

Do not commit a `.jks`, private key, password, or base64 keystore value to the repository.

## Production workflow contract

`.github/workflows/android-production-release.yml` is owner-triggered and build-only. It requires `TheHighBrid` as the actor, an exact current `main` SHA, a semantic version name, a version code greater than the v2.1.0 baseline of `210`, and a matching `v<version>` tag value.

The workflow fails closed when any signing secret is missing or invalid. It never falls back to `assembleDebug`. It also compares the APK's actual signing certificate fingerprint against `JOBTOMATIK_RELEASE_CERT_SHA256`.

For every production update, the source branch must carry the new Android `versionCode` and `versionName` in `frontend/android/app/build.gradle`. The production workflow verifies that the requested version exactly matches the source tree and that the version code is greater than `210`. This creates a monotonically increasing release identity instead of allowing an accidental reuse of an installable version code.

The workflow does **not** publish a GitHub release. Publication remains a separate owner-controlled release action after the signed artifact has been reviewed.

## One-time migration from v2.1.0

The public v2.1.0 Android package was development-signed. Android package updates require the installed package and replacement package to use the same signing identity. Therefore, the first persistent-release-signed APK cannot be treated as an in-place update of that existing development-signed v2.1.0 installation.

The migration boundary is:

1. finish or safely pause any active supervised application workflow;
2. preserve the Termux/Ubuntu backend and its application data;
3. export or otherwise retain any user-managed local settings that are outside the backend database when applicable;
4. remove the development-signed Android client only when no active browser/application handoff depends on it;
5. install the first persistent-release-signed client;
6. reconnect it to the existing backend at the configured local API address;
7. verify the backend data and current application state before continuing work.

**Do not perform this migration during an active supervised submission or retained-browser handoff.** The APK is a client. Backend data, résumé files, browser handoff state, and Termux/Ubuntu runtime data are not stored as the APK's signing identity and must be preserved separately.

After this one-time boundary, subsequent production APKs signed by the same persistent certificate can use Android's normal in-place update path, subject to the normal Android version and package rules.

## Evidence retained per build

A successful production artifact contains:

- the APK;
- APK SHA-256 checksum;
- `APK-BADGING.txt` with package/version identity;
- `APK-SIGNING.txt` with the certificate verification output;
- `SOURCE-COMMIT.txt`;
- `BUILD-INFO.txt` containing the source SHA, version code/name, release tag, signing mode, and certificate SHA-256.

These artifacts are evidence of what was built and signed. They do not by themselves authorize publication or a real-world application action.
