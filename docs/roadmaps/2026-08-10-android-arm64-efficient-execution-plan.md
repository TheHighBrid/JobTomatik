# Android ARM64 Efficient Execution Plan

**Audit date:** 2026-08-10  
**Target environment:** Android ARM64, Termux, Ubuntu/proot, and Termux-native Chromium

## Audit conclusion

The phone can be the primary always-on development and shadow-runtime host, but it should not pretend to be every release environment. The efficient design splits work by capability: Termux owns native Chromium and device controls; Ubuntu/proot owns Python services and deterministic tests; CI or a conventional Linux host owns Docker, managed-Playwright, Gradle, signing, and exact release-matrix lanes that are unavailable or disproportionately expensive on the phone.

Run this first on every host:

```bash
bash scripts/verify.sh device
```

The command is read-only. It identifies the runtime profile and recommends a gate without enabling submission, outreach, autopilot, or maturity promotion.

## Capability-aware lane map

| Lane | Android/Termux ARM64 | Ubuntu/proot ARM64 | CI or conventional Linux |
|---|---|---|---|
| Native Chromium/CDP, Android UI, reconnect checks | **Primary** | Connect to Termux CDP | Optional |
| FastAPI, SQLite, Redis, Celery worker/Beat | Supervisor only | **Primary** | Reproduction |
| Focused Python tests and campaign evaluators | Possible | **Primary** | Required repeat |
| Managed Playwright browser matrix | Do not install as a substitute | Defer | **Primary** |
| Docker Compose | Defer | Defer | **Primary** |
| Capacitor/Gradle lint, assemble, signing | Only when the full pinned SDK is intentionally installed | Usually defer | **Primary** |
| 4h/8h/24h real shadow duration | **Primary candidate** | **Primary services** | Independent review |

An unavailable lane is a recorded blocker or delegated check, never a pass. Native Chromium evidence and managed-Playwright results are complementary and must not be relabelled as one another.

## Faster critical path from the current checkpoint

1. **Preserve Days 12–15 evidence.** Re-run the read-only Days 12–22 evaluator and its tests after relevant code or evidence-schema changes; do not regenerate canonical evidence merely to refresh timestamps.
2. **Prepare Days 16–22 without premature execution.** Test preflight, payload binding, idempotency, confirmation review, and promotion evaluators with fixtures. Real submissions remain separately user-gated and evidence-backed.
3. **Parallelize future readiness by cost, not by roadmap date.** On the phone, test scheduler, recovery, runtime identity, external CDP, and shadow provenance now. Run managed-browser, Docker, Android build, dependency, and full backend matrices once per exact candidate SHA on capable CI rather than repeatedly emulating them in proot.
4. **Use one immutable candidate SHA.** Start API, worker, Beat, frontend, and Chromium against the same revision. If code changes, invalidate the duration campaign and restart rather than mixing evidence.
5. **Promote only after retained evidence.** Future-day fixtures and green evaluators prove readiness infrastructure, not completion, certification, submission, or release authority.

## Phone-optimized check ladder

Run cheap checks first so failures do not waste battery or a long shadow window:

```bash
# Termux or any host: classify capabilities
bash scripts/verify.sh device

# Ubuntu/proot: syntax and focused future-control tests
python -m compileall -q app tests
python -m pytest -q --tb=short \
  tests/test_campaign_day_gates.py \
  tests/test_scheduler_policy.py \
  tests/test_dead_letter_recovery.py \
  tests/test_runtime_identity_shadow_gate.py \
  tests/test_external_cdp_runtime.py \
  tests/test_shadow_evidence_provenance.py

# Read-only campaign truth check
PYTHONPATH=. python scripts/evaluate_campaign_days_12_22.py

# Managed Android stack, only after its venv and native dependencies exist
bash scripts/manage_android_stack.sh status
```

Then pin the candidate SHA and use capable CI for:

```bash
bash scripts/verify.sh dependencies
bash scripts/verify.sh backend
bash scripts/verify.sh frontend
bash scripts/verify.sh deployment
bash scripts/verify.sh android
```

Do not start a duration campaign until the exact Android readiness markers in `docs/ANDROID_SHADOW_RUNTIME_READINESS.md` pass. Keep `ALLOW_REAL_APPLICATION_SUBMIT=false` and outreach disabled throughout shadow work. `AUTOPILOT_ENABLED=true`, when required for a shadow scheduler, is an explicit campaign decision and does not authorize a real application.

## Resource policy for a phone

- Keep SQLite and runtime artifacts in the Ubuntu filesystem rather than shared Android storage; shared storage has weaker Unix semantics and higher I/O cost.
- Use one Celery worker with bounded concurrency and the isolated Android Redis DB already defined by the manager. Avoid duplicate workers after Termux or Android process reclamation.
- Keep the phone charging, disable battery optimization for Termux, maintain adequate free storage, and verify thermal stability before 8h/24h runs.
- Use Chromium remote debugging only on loopback. Do not expose CDP to the LAN or internet.
- Retain logs and hash-bound reports, but rotate transient Vite, worker, and browser logs between failed rehearsals so storage pressure cannot corrupt a real campaign.
- Prefer focused test selections during iteration; reserve full suites, dependency downloads, and APK builds for a clean exact-head candidate.

## Exit criteria

This adaptation is successful when the phone stack is reproducible and attested, external-CDP dry-run boundaries are green, recovery survives process interruption, and a capable independent lane repeats the exact-head release checks. None of those results alone changes adapter maturity or authorizes live submission.
