# Security Policy

## Supported version

Security fixes are maintained for the latest `1.x` release on `main`.

## Reporting a vulnerability

Use GitHub’s private vulnerability-reporting or Security Advisory feature for this repository when available. Do not place access tokens, applicant data, résumé contents, signing keys, verification codes, or a working exploit in a public issue.

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

Protect the backend database, `uploads/`, `handoff_sessions/`, environment files, backups, and device storage. The Android manifest disables application backup, but backend files remain the operator’s responsibility.

## Required secret practices

- Replace the default `SECRET_KEY` before real use.
- Keep `SECRET_KEY` stable after issuing authentication tokens.
- Set and preserve `ANSWER_VAULT_KEY` when separating answer-policy encryption from the JWT secret.
- Never commit `.env`, API keys, résumé files, databases, browser profiles, or handoff screenshots.
- Never type verification codes into logs or issue comments.
- Keep real submission and unattended automation disabled unless a reviewed release gate explicitly requires them.

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

JobTomatik does not bypass CAPTCHA, anti-bot, MFA, login, assessment, or identity-verification controls. It pauses and gives the authenticated user limited control of the retained browser. Any change that silently solves, evades, or suppresses these controls is outside the v1 security model.

## Submission safety boundary

The defaults must remain:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
AUTOPILOT_ENABLED=false
```

Confirmation evidence is required before JobTomatik marks an application submitted or confirmed. A missing or ambiguous confirmation must fail closed and require review.
