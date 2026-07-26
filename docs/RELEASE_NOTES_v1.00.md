# JobTomatik v1.00

JobTomatik v1.00 is the first complete supervised foundation release on the roadmap to fully autonomous job discovery, preparation, application, and evidence-backed real submission.

## Highlights

- Job search, scoring, review queue, résumé handling, and cover-letter preparation.
- Encrypted Answer Policy Vault with exact-option validation.
- Greenhouse retained-browser handoff for CAPTCHA and verification boundaries.
- Expired-code recovery with request-new-code, back, reload, restart, and replace-and-submit controls.
- Explicit employer confirmation-page detection and submission evidence.
- Automatic closure of successful handoffs and confirmed application state.
- Android Capacitor client with reproducible Gradle and GitHub Actions builds.
- Full Android/Termux/Ubuntu installation and recovery tutorial.
- Adapter maturity and release-gate infrastructure for progressive promotion toward autonomous execution.

## Product direction

The final JobTomatik operating goal is fully autonomous real submission for certified application paths. Version 1.00 establishes the supervised and evidence-producing foundation needed to develop, test, and promote that capability safely adapter by adapter.

Development builds begin with conservative release-gate values. Those defaults describe the current rollout stage, not a permanent supervised-only product definition.

JobTomatik does not attempt to evade CAPTCHA, anti-bot, login, MFA, assessment, or identity-verification controls. When a third-party service explicitly requires a human action, the retained-browser system can pause, request the action, and resume afterward.

## Android

- Application ID: `ca.jobtomatik.app`
- Version name: `1.0.0`
- Version code: `100`
- Minimum SDK: 23
- Target SDK: 35

The APK is a client. Run the FastAPI backend, Redis, and Celery worker separately, then connect the Android app to `http://127.0.0.1:8010` for the same-device Termux/Ubuntu setup.

Read the release `BUILD-INFO.txt` to confirm whether the APK uses permanent release signing or the development-signing fallback.
