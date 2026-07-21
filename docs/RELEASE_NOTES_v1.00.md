# JobTomatik v1.00

JobTomatik v1.00 is the first complete supervised release of the project.

## Highlights

- Job search, scoring, review queue, résumé handling, and cover-letter preparation.
- Encrypted Answer Policy Vault with exact-option validation.
- Greenhouse retained-browser handoff for CAPTCHA and verification boundaries.
- Expired-code recovery with request-new-code, back, reload, restart, and replace-and-submit controls.
- Explicit employer confirmation-page detection and submission evidence.
- Automatic closure of successful handoffs and confirmed application state.
- Android Capacitor client with reproducible Gradle and GitHub Actions builds.
- Full Android/Termux/Ubuntu installation and recovery tutorial.

## Important boundary

Real and unattended application submission remain disabled by default. JobTomatik v1.00 is designed for human-supervised use and does not bypass CAPTCHA, anti-bot, login, MFA, assessment, or identity-verification controls.

## Android

- Application ID: `ca.jobtomatik.app`
- Version name: `1.0.0`
- Version code: `100`
- Minimum SDK: 23
- Target SDK: 35

The APK is a client. Run the FastAPI backend, Redis, and Celery worker separately, then connect the Android app to `http://127.0.0.1:8010` for the same-device Termux/Ubuntu setup.

Read the release `BUILD-INFO.txt` to confirm whether the APK uses permanent release signing or the development-signing fallback.
