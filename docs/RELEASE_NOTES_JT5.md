# JT5 integration notes

**As of:** 2026-10-16. **Main integration:** #704, commit `6aac5b33701db6d13952f86c1faaeca76d66810f`.

JT5 provides a simplified, target-bound owner Apply flow and advances the fully autonomous job-hunt product. Integration is complete for the recorded implementation, but a new public JT5 release and general autonomous certification are not established by that merge.

## Integrated changes

- Owner-authenticated Apply reserves and dispatches a durable attempt; read-only status follows progress.
- Atomic claims, target identity and retained outcomes prevent blind duplicate execution.
- Public reserve-only execution was removed.
- OneHost startup reconciles interrupted attempts before worker consumption.
- Retained owner browser interaction, UTC leases, private native input and once-only final-action checkpoints are integrated.
- Pending-review persistence, transient viewer recovery and nonblocking database locks are repaired.
- Uncertainty remains visible after a final action or manual Applied selection.

## Verification and deployment

The #704 implementation head `1a8a0c7be8476894c51dfba5e62ea7a8b936d5fd` has 25 successful checks and two skipped checks. The merge tree matches that head. OVH deployment of the implementation is recorded; host administration was offline during the documentation refresh. See [evidence](EVIDENCE.md).

## Known limitations

- #706 corrects the JT5 bypass of `ALLOW_REAL_APPLICATION_SUBMIT` and withdrawn-state handling. It is an undeployed draft with Codacy action required at this snapshot.
- Evidence-backed reconciliation of uncertain attempts and known pre-browser exception classification remain follow-up work.
- One recorded owner final action remains without employer confirmation. Manual Applied status is not receipt evidence.
- General unattended operation and universal ATS coverage are not certified.

## Version and publication

Repository/Android defaults remain 2.1.1, code 211. Latest published GitHub release observed is v2.1.0. JT5 is an architecture name, not a new version assignment. This documentation does not create a tag, sign an APK or publish a release.

Complete the [current cutover checklist](operations/JT5_PRODUCTION_CUTOVER_CHECKLIST.md) before promoting a corrected build. Real-world actions and production enablement remain within exact owner authorization.
