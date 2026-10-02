# OneHost phase 0 contract

Locked 2026-10-02.

Freeze Android execution. No new ADB, PRoot, native-Chrome, Android browser transport, or CDP recovery work.

Phase 0 path: existing FastAPI/Celery application path to `form_filler_v2.py` `chromium.launch()` against the Greenhouse HTML already in `backend/tests/test_greenhouse_adapter.py`.

Success requires an owned Chromium launch, fixture load, filled fields, a Playwright trace, persisted evidence, and a clean shutdown, repeated without user intervention.

No employer site, phone, submit, APK change, browser-provider, browser container, viewer, or new ADB work.

Gate 2 is one Greenhouse dry-run, and only after this proof is green.

If the local fixture still needs ADB, external Chrome, or cross-process leasing, question the architecture. Do not question the product.
