# Security Policy

## Supported version

Security fixes are maintained for the latest `1.x` release on `main`.

## Reporting a vulnerability

Use GitHub's private vulnerability-reporting or Security Advisory feature for this repository when available. Do not place access tokens, applicant data, résumé contents, signing keys, verification codes, or a working exploit in a public issue.

Include:

- affected commit or release;
- the smallest reproducible scenario;
- expected and actual behavior;
- whether applicant data, browser sessions, submission state, or secrets are exposed;
- suggested mitigation, when known.

## Local data handled by JobTomatik

A JobTomatik installation may store:

- account and profile details;
- résumé files;
- cover letters and application answers;
- encrypted answer-policy values;
- job and application records;
- retained-browser metadata and screenshots;
- submission evidence;
- notification and follow-up history.

Protect the backend database, `uploads/`, `handoff_sessions/`, browser profile directories, environment files, backups, and device storage. The Android manifest disables application backup, but backend files remain the operator's responsibility.

## Required secret practices

- Replace the default `SECRET_KEY` before real use.
- Keep `SECRET_KEY` stable after issuing authentication tokens.
- Set and preserve `ANSWER_VAULT_KEY` when separating answer-policy encryption from the JWT secret.
- Never commit `.env`, API keys, résumé files, databases, browser profiles, or handoff screenshots.
- Never type verification codes into logs or issue comments.
- Treat real-submission and autonomous-operation flags as controlled release gates. Promote them only in builds whose adapters, evidence, duplicate protection, recovery behavior, and operational limits meet the operator's readiness criteria.

## Android signing

The repository contains no private signing key or signing password.

Release signing accepts these environment variables:

```text
JOBTOMATIK_KEYSTORE_PATH
JOBTOMATIK_KEYSTORE_PASSWORD
JOBTOMATIK_KEY_ALIAS
JOBTOMATIK_KEY_PASSWORD
```

GitHub Actions may instead receive a base64-encoded keystore through repository secrets. Preserve the private key used for any distributed APK. Android will not install an update over an existing app when the new APK is signed by a different key.

If the release workflow has no permanent signing secrets, it may publish a development-signed personal-install build. Treat that certificate as temporary and read the included `BUILD-INFO.txt` before installing or upgrading.

## Network guidance

The Android client permits cleartext traffic because the reference installation connects to a same-device backend at `http://127.0.0.1:8010`. Use HTTPS and a narrowly configured `CORS_ORIGINS` value when the backend is hosted anywhere else. Do not expose the development FastAPI or Redis ports directly to the public internet.

## Human-verification boundary

JobTomatik does not attempt to evade CAPTCHA, anti-bot, MFA, login, assessment, or identity-verification controls. When a third-party service explicitly requires a human action, the system pauses, preserves state, requests the action, and resumes afterward when possible.

This boundary does not redefine JobTomatik as permanently supervised. The product direction remains fully autonomous operation for the portions of the job-application workflow that can be completed legitimately and reliably without a required human verification step.

## Submission integrity

Development builds currently ship with conservative release-gate values:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
AUTOPILOT_ENABLED=false
```

These values are staging defaults, not a permanent product restriction. A promoted autonomous release may enable the relevant controls after the operator accepts its certification evidence and operating profile.

Confirmation evidence is required before JobTomatik marks an application submitted or confirmed. A missing or ambiguous confirmation must not be recorded as success. Duplicate prevention, idempotency, caps, circuit breakers, and operator kill switches remain valid safeguards in both supervised and autonomous modes.
