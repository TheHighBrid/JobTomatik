# Release manifest

`build_release_manifest` binds a release candidate to explicit, exact identity
fields before any publication or rollback decision:

```text
source_sha
version
android_version_code
apk_sha256
signing_cert_sha256
backend_revision
frontend_revision
database_schema_revision
verification_runs
build_timestamp
```

Every field above must be supplied. Source and revision SHAs require exact
40-character hexadecimal values, artifact and certificate digests require exact
SHA-256 values, and `build_timestamp` must be timezone-aware ISO-8601.

The backend revision must equal `source_sha`. Missing or malformed identity,
an empty verification set, or a destructive schema transition fails closed.
The manifest records rollback and upgrade test claims but never grants submit
authority.
