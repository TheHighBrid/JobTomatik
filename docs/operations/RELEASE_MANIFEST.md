# Release manifest

`build_release_manifest` writes the canonical OneHost release identity:

```
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

Missing hashes, a backend revision that is not the source SHA, or a destructive
rollback fail closed. The manifest does not grant submit authority.
