# JobTomatik Full Engineering Audit

Date: 2026-07-27  
Audited baseline: `main` at `42e64ef35152e728f62d4ce68c3a661063e39c02`  
Remediation branch: `agent/full-audit-hardening`

## Executive decision

JobTomatik is a substantially developed application, not a prototype shell. Its strongest area is submission integrity: adapter maturity boundaries, reviewed-submission gates, duplicate protection, retained handoffs, evidence reconciliation, and conservative release defaults are all represented in code and regression tests.

The principal weaknesses were operational rather than conceptual. The baseline could start a sensitive runtime with a placeholder signing secret, silently ignore compatibility-migration failures, accept an unsafe remote HTTP API address in the client, and had no frontend runtime tests or automated dependency maintenance. These gaps are corrected on the remediation branch.

### Engineering readiness score

This is an internal engineering score, not an external security certification.

| Area | Baseline | Remediated | Notes |
|---|---:|---:|---|
| Architecture and separation | 9/10 | 9/10 | Clear backend, worker, client, Android, adapter, and evidence boundaries |
| Submission integrity | 9/10 | 9/10 | Strong safety gates and evidence-oriented workflow |
| Authentication and secrets | 6/10 | 9/10 | Placeholder-secret and bcrypt boundary protections added |
| Data and privacy handling | 7/10 | 8/10 | Email logs redacted; remaining secure-token-storage work noted below |
| Reliability and startup behavior | 7/10 | 9/10 | Schema drift now fails visibly; database readiness probe added |
| Frontend resilience | 6/10 | 9/10 | Storage recovery, URL validation, request timeout, tests, and accessibility added |
| CI and supply chain | 7/10 | 9/10 | Frontend tests, Dependabot, and CodeQL added |
| Deployment maturity | 6/10 | 8/10 | Compose process behavior improved; production profile remains future work |
| Documentation and operability | 9/10 | 9/10 | Existing setup, release, and security documentation is unusually complete |
| **Overall** | **76/100** | **88/100 pending CI** | Remaining work is listed in the residual-risk register |

## Audit scope

The review covered:

- repository structure and recent maintenance history;
- FastAPI startup, configuration, authentication, database access, uploads, and email delivery;
- React API transport, authentication persistence, routing shell, mobile navigation, and registration;
- Celery, Redis, retained-browser, ATS adapter, evidence, and release-gate architecture;
- Docker Compose and container entry behavior;
- GitHub Actions, test gates, dependency maintenance, and security scanning;
- Android release configuration and documented operating boundary;
- secret handling, personal-data exposure, and operational recovery documentation.

## Existing strengths confirmed

### Submission safety and evidence

The repository has a deliberate adapter-maturity model rather than a single unrestricted auto-submit switch. Real submission is gated independently from discovery and form preparation. Employer confirmation evidence, idempotency, duplicate protection, retained-browser recovery, pilot ledgers, and independent evidence review are represented across the backend and test suite.

### Conservative defaults

The default release profile keeps real submission, supervised pilots, resumable live handoffs, and autopilot disabled. This is the correct fail-safe posture for a system that acts on external hiring platforms.

### Applicant-file handling

Résumé uploads are streamed in bounded chunks, limited to 10 MB, assigned server-controlled filenames, checked for a PDF signature, and stored outside the original user filename path.

### Repository hygiene

The repository excludes environment files, databases, uploads, browser profiles, handoff artifacts, Android signing material, APKs, and common build outputs. Security and release documentation explicitly warn against exposing applicant data and verification material.

### Regression depth

The backend has extensive tests around adapters, handoffs, target identity, evidence, submission approval, duplicate protection, recovery, certification boundaries, and release contracts. This is a strong foundation for continued development.

## Findings corrected on the remediation branch

### F-01: Sensitive runtime accepted a placeholder JWT secret

**Severity:** High  
**Status:** Fixed

The baseline configuration provided a known development secret and did not distinguish development from production. A deployment could enable real-submission controls while still using that placeholder.

Remediation:

- added `APP_ENV` with `development`, `test`, and `production` profiles;
- added explicit security validation at settings load;
- production and real-submission pilot modes reject placeholder or sub-32-byte secrets;
- wildcard credentialed CORS is rejected;
- invalid supervised-approval TTL relationships are rejected;
- API documentation can be disabled through `ENABLE_API_DOCS`.

### F-02: Database compatibility migrations failed silently

**Severity:** High  
**Status:** Fixed

The startup compatibility migration caught broad exceptions and continued. The service could therefore appear healthy while its schema was only partially upgraded.

Remediation:

- migration failures are logged with the exact target;
- failed compatibility migrations now stop startup;
- a database-backed `/api/system/ready` probe distinguishes process health from database readiness;
- Docker health checks now use the readiness probe.

### F-03: API URL normalization could break local setup or expose tokens

**Severity:** High  
**Status:** Fixed

The client prepended HTTPS whenever a manually entered address lacked a scheme. This broke common local addresses such as `127.0.0.1:8010`. Conversely, an explicitly entered public HTTP address was accepted, allowing bearer tokens to travel without transport encryption.

Remediation:

- local, emulator, `.local`, and private-network hosts infer HTTP;
- public hosts infer HTTPS;
- public HTTP endpoints are rejected;
- embedded credentials, query strings, and URL fragments are rejected;
- a duplicated trailing `/api` is removed safely;
- API requests now have a bounded timeout;
- failed login and registration requests no longer trigger global unauthorized redirects.

### F-04: Password policy did not match bcrypt boundaries

**Severity:** High  
**Status:** Fixed

Account creation accepted passwords without a minimum length or bcrypt byte-limit validation. Unicode input can exceed bcrypt's 72-byte boundary with far fewer than 72 characters.

Remediation:

- registration requires at least eight characters;
- passwords above 72 UTF-8 bytes are rejected before hashing;
- verification treats malformed or oversized input as a normal authentication failure;
- JWT expiry timestamps are timezone-aware;
- JWT subjects are parsed as integers and malformed subjects are rejected;
- backend and frontend tests now cover these boundaries.

### F-05: Synchronous email delivery ran inside async request paths

**Severity:** Medium  
**Status:** Fixed

The SendGrid SDK is synchronous but was called directly from async functions, which could block the FastAPI event loop. Mock email logging also included complete message bodies that may contain applicant or hiring details.

Remediation:

- SendGrid delivery runs through `asyncio.to_thread`;
- mock logs include recipient domain, subject, and body length only;
- exceptions use structured stack logging without printing message content.

### F-06: Corrupt browser storage could crash the client

**Severity:** Medium  
**Status:** Fixed

The authentication store parsed persisted user JSON during module initialization without protection. A malformed value could prevent the application from loading.

Remediation:

- added guarded storage access for restricted WebViews and private mode;
- malformed JSON is removed and replaced by a safe fallback;
- the API client and Zustand store now share the same storage abstraction;
- Node runtime tests verify recovery behavior.

### F-07: Frontend had no automated runtime regressions

**Severity:** Medium  
**Status:** Fixed

The frontend production build was checked, but logic such as URL normalization and storage recovery had no tests.

Remediation:

- added zero-dependency Node tests for API URL security and storage recovery;
- added `npm test`;
- integrated the tests into the main stabilization workflow before the production build.

### F-08: Dependency maintenance was manual

**Severity:** Medium  
**Status:** Fixed

Python, npm, Gradle, and GitHub Actions dependencies had no repository-level update automation.

Remediation:

- added monthly Dependabot coverage for pip, npm, Gradle, and GitHub Actions;
- grouped frontend production and development updates to reduce pull-request noise.

### F-09: No repository SAST workflow

**Severity:** Medium  
**Status:** Fixed

The repository had extensive behavioral tests but no general static security analysis.

Remediation:

- added CodeQL scanning for Python and JavaScript/TypeScript;
- scans run on pull requests, pushes to `main`, weekly schedule, and manual dispatch;
- permissions are limited to repository read plus security-event upload.

### F-10: Mobile navigation and polling had avoidable UX debt

**Severity:** Low to Medium  
**Status:** Fixed

Icon-only navigation controls lacked accessible labels, the overlay was not keyboard-operable, Escape did not close the panel, and notification polling continued while the app was hidden.

Remediation:

- added labels, expanded state, dialog semantics, Escape handling, and accessible overlay controls;
- polling pauses while hidden and refreshes when the app becomes visible;
- state updates are guarded after unmount.

### F-11: Compose API process used development reload behavior

**Severity:** Low to Medium  
**Status:** Fixed

The default backend container used `uvicorn --reload`, increasing file-watcher overhead and restart noise in the documented Docker quick start.

Remediation:

- removed reload from the default container command;
- enabled init process handling for frontend, backend, worker, and beat services;
- exposed runtime profile and documentation controls consistently;
- parameterized the PostgreSQL password while retaining a local-development fallback.

## Residual risk register

These items are not hidden. They should be handled as the product moves from personal/local operation toward a hosted or multi-user service.

### R-01: Bearer tokens remain in browser local storage

**Priority:** High before a broadly distributed hosted release

The resilience of local storage is improved, but a successful script injection could still read the token. Capacitor should use a vetted native secure-storage plugin. A hosted browser version should consider short-lived access tokens with refresh-token rotation in secure, HTTP-only cookies or another carefully designed session model.

### R-02: Authentication rate limiting and abuse controls

**Priority:** High for any internet-exposed backend

Login and registration do not have dedicated per-account and per-network throttling. Add Redis-backed rate limits, progressive delay, audit events, and alerting. Keep error responses resistant to account enumeration where the deployment model requires it.

### R-03: Dual schema-management paths

**Priority:** Medium

The application uses both Alembic and startup-time additive compatibility migrations. The remediation makes failures visible, but the long-term target should be Alembic as the single authoritative schema path, with startup limited to revision verification.

### R-04: Broad exception handling in browser automation

**Priority:** Medium

Browser and ATS integrations legitimately need defensive exception boundaries, but broad catches are common. Continue classifying expected Playwright errors separately from unknown defects, preserve structured reason codes, and add metrics for swallowed/recovered failures.

### R-05: Production deployment profile

**Priority:** High before public hosting

The Docker Compose file remains a local-development topology with bind mounts and direct service composition. A production profile should add a TLS reverse proxy, non-root images, immutable application layers, managed secrets, restricted networks, backup automation, centralized logs, and database migration as a one-shot release step.

### R-06: GitHub Actions references are version-tag pinned, not commit pinned

**Priority:** Medium

Workflow actions use major-version tags. For stronger supply-chain controls, pin third-party actions to reviewed commit SHAs and let Dependabot update those references.

### R-07: Frontend end-to-end coverage

**Priority:** Medium

The new tests cover runtime utilities, while React flows still rely mainly on build success and backend API tests. Add Playwright UI tests for registration, login, API connection setup, job queue, application review, retained handoff, and completed-application control suppression.

### R-08: Android device and secure-storage validation

**Priority:** Medium

Gradle lint and APK assembly are valuable but do not replace device tests. Add instrumentation or emulator tests for network configuration, process resume, notification polling, upload selection, back navigation, and future secure-token storage.

### R-09: Observability and incident response

**Priority:** Medium

Add structured request IDs, user-safe correlation IDs, task IDs across FastAPI and Celery, metrics for adapter outcomes, submission uncertainty, handoff expiry, circuit-breaker activation, and a documented incident export that excludes applicant secrets.

### R-10: Release provenance and software inventory

**Priority:** Medium

The release process already creates checksums. Add an SBOM, provenance attestation, dependency-vulnerability report, and signed release metadata for stronger auditability.

## Recommended next implementation sequence

1. Merge the remediation branch after all GitHub checks pass.
2. Add Redis-backed authentication rate limiting.
3. Move Android authentication tokens to native secure storage.
4. Create a production deployment profile with TLS and managed secrets.
5. Consolidate schema upgrades under Alembic.
6. Add React end-to-end tests and Android emulator smoke tests.
7. Pin workflow actions to reviewed commit SHAs.
8. Add structured observability, SBOM, and release provenance.

## Validation gates for this remediation

The pull request should not be merged unless all applicable checks pass:

- Python compilation;
- complete backend pytest suite;
- security-hardening regression tests;
- Alembic migration smoke test;
- frontend Node runtime tests;
- frontend production build;
- Docker Compose rendering and fail-safe flag checks;
- CodeQL Python analysis;
- CodeQL JavaScript/TypeScript analysis.

## Files changed by the remediation

The branch intentionally limits changes to configuration, authentication, startup reliability, email delivery, frontend runtime behavior, tests, CI security, deployment configuration, and documentation. ATS submission logic, certification evidence, application-target identity, and the open Lever pilot-ledger work are not modified, reducing conflict with active feature development.
