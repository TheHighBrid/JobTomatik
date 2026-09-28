# Working Android browser baseline — 2026-09-27

Physical device verification established a working hybrid baseline:

- repository/runtime revision: `8185547ee2d5a352c61eefb1113f8ef466446f8a`
- static frontend artifact: matching `8185547...`
- historical native launcher installed from the Sep 25 working implementation
- Sep 25 application-flow behavior restored for:
  - `backend/app/models/answer_policy.py`
  - `backend/app/services/answer_policy.py`
  - `backend/app/services/browser_handoff.py`
  - `backend/app/services/operator_assisted_question_retention.py`
- native Chrome application tab visibly opens on physical Android
- JobTomatik fills the Lever application through the final-ready boundary
- `ANDROID_FRONTEND_TABS_REFRESHED=1`
- `ANDROID_RUNTIME_ACCEPTANCE=PASS`

This baseline must remain recoverable while final-submit automation is developed. A failed final-submit experiment must not modify ADB discovery, native launcher, CDP transport, controlled-tab creation, or the browser-popup path.
