# Ashby native Chrome certification lane

This branch is the live-certification lane for Ashby on the current Android/native-Chrome runtime.

## Acceptance contract

Ashby is certified only when a real public Ashby application proves target resolution, retained-tab resume, supported field and upload filling, Answer Vault recovery for unknown questions, operator-authorized final submission, strong post-submit confirmation detection, durable evidence persistence, automatic Applied reconciliation, and duplicate/retry suppression.

Synthetic and CI tests are prerequisites, not certification evidence.

## Versioning rule

The base Ashby adapter remains at its existing fail-closed version until the live certification boundary is actually earned. The registered certification wrapper may describe already-earned synthetic and handoff boundaries independently. Do not bump the base adapter merely to open a certification lane because frozen evidence and release gates intentionally bind that source digest.
