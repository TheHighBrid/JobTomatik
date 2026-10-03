# Fixture-first recovery contract

Owner direction adopted on 2026-10-02, America/Toronto.

Freeze Android execution work. Do not add ADB, PRoot, native-Chrome transport or
cross-process lease recovery. Keep the product, FastAPI, Postgres, Redis, Celery,
the Answer Policy Vault, adapters, evidence, and APK.

## Gate 1

Run `bash scripts/verify-onehost-fixture.sh` on a Docker-capable Linux runner.
It reuses `backend/Dockerfile`; there is no new browser image, provider or viewer.
The browser and a loopback HTTP fixture are owned and stopped by one process.
The fixture container has no external network and publishes no host ports.

Required evidence:

1. Three independent Chromium launches, each navigating to a fresh HTTP fixture.
2. Read-back verification of fields filled by the current production v3 field
   filler and bounded ATS flow.
3. DOM observations and HTTP records proving final Submit was never clicked or
   sent. A log entry alone does not satisfy this check.
4. A valid Playwright trace and JSON evidence retained outside the container for
   every attempt, including failed attempts after browser startup.
5. Browser/driver child-process exit and fixture-server shutdown after each run.
6. Negative controls proving fill failures, unexpected network requests and even
   a synthetic submit click fail the proof while retaining diagnostic traces.
7. The exact checked-out commit and source digest in the retained summary.

The dedicated GitHub Actions job runs the actual Compose command and retains
the proof, traces, build log, test output and rendered configuration. Local
non-Docker browser tests are supporting evidence, not a substitute for Compose.

All evidence is synthetic. Gate 1 does not certify employer submission, adapter
maturity, API/Celery job dispatch, retained handoffs, or an APK deployment.
The present API dry-run facade selects the retained runner. Its orchestration
has not been proven by this smaller gate, and must not be described as proven.

## Gate 2

One Greenhouse dry-run follows only after Gate 1 has passed. Preserve all genuine
security, answer, confirmation and duplicate boundaries. No real submission is
part of either recovery gate. Nothing else enters the recovery lane until both
gates have evidence.

If the local fixture requires ADB, an externally owned Chrome process or
cross-process lease recovery, question the execution architecture. Do not treat
that as evidence that the product is infeasible.

## Owner intervention

Never use the owner as a troubleshooting agent. Investigate, reproduce, inspect
logs, eliminate alternatives and complete independent verification off-device.
Owner involvement is limited to a genuine human gate requiring their access,
authorization, identity, sensitive answer or unique judgment, or final execution
acceptance after multiple thorough independent tests have passed, verification
has been achieved, and no viable alternative to owner involvement remains.
Explain the verified remaining boundary and request only the smallest necessary
action. A failed command or an uncertain implementation is not a human gate.

The owner granted full repository engineering authorization in this session.
Routine reversible repository work does not require another approval. Real-world
submissions, communications, paid commitments and identity actions retain their
specific authorization boundaries.
