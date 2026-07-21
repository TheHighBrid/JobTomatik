# JobTomatik v1.00 Release Checklist

## Source

- [ ] `VERSION` is `1.0.0`.
- [ ] Android `versionCode` is `100` and `versionName` is `1.0.0`.
- [ ] No signing key, password, database, résumé, `.env`, APK, or AAB is tracked.
- [ ] Gradle wrapper uses the official Gradle distribution URL.
- [ ] `main` contains no open release-blocking pull request.

## Verification

- [ ] Backend pytest suite passes.
- [ ] Python compilation passes.
- [ ] Alembic migration smoke test passes.
- [ ] Retained-browser certification passes.
- [ ] Frontend production build passes.
- [ ] Android lint passes.
- [ ] Android APK assembly passes.
- [ ] `aapt dump badging` reports `ca.jobtomatik.app`, version code `100`, version name `1.0.0`.
- [ ] Docker Compose renders with real submit and autopilot disabled.

## Documentation

- [ ] README reflects v1.00 and supervised boundaries.
- [ ] `docs/SETUP_TUTORIAL.md` covers clean installation through confirmation.
- [ ] `CHANGELOG.md` contains the 1.0.0 entry.
- [ ] `SECURITY.md` documents secrets, signing, and local data.
- [ ] `docs/FINAL_AUDIT_v1.00.md` records accepted boundaries.

## Release

- [ ] Merge finalization PR to `main`.
- [ ] Create branch `release/v1.0.0` from the verified merge commit.
- [ ] Release workflow passes backend and Android jobs.
- [ ] GitHub release `v1.0.0` is published as **JobTomatik v1.00**.
- [ ] Release contains APK, SHA-256 file, APK badging, and `BUILD-INFO.txt`.
- [ ] APK signing mode is reviewed before installation.

## Post-release smoke test

- [ ] Install APK.
- [ ] Connect to `http://127.0.0.1:8010`.
- [ ] Register/login.
- [ ] Load profile and résumé.
- [ ] Search and approve a non-sensitive test posting.
- [ ] Run one Dry Run.
- [ ] Open and refresh a retained handoff.
- [ ] Verify confirmation evidence closes the handoff.
- [ ] Verify completed record hides further submission controls.
- [ ] Confirm safety flags remain disabled.
