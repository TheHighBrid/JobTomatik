# Recovery Gate 2 evidence runner

Gate 2 proves the production `GreenhouseAdapter`, production v3
`_fill_step_fields`, bounded `run_ats_application_flow`, and one Playwright-owned
Chromium against one public HTTPS Greenhouse board/job form. It does not certify
submission readiness, API/Celery dispatch, adapter maturity, autonomous submission,
or an APK deployment. Gate 1 and recovery/security integration remain prerequisites.

The dedicated `Recovery Gate 2 synthetic verification` workflow executes real
Chromium with in-memory HTTPS fixtures. Those artifacts are explicitly synthetic.
All required canonical exact-head workflows and affected backend/browser suites
must pass before the public run. No public run is scheduled by this workflow.

After verification, run from a clean committed checkout with backend dependencies
and Playwright Chromium installed:

```sh
cd backend
PYTHONPATH=. python scripts/run_recovery_gate2.py \
  --url https://job-boards.greenhouse.io/BOARD/jobs/JOB_ID \
  --evidence /absolute/path/to/new-evidence-directory \
  --ledger /absolute/path/to/persistent-gate2-ledger.sqlite
```

Use exactly one public target. The ledger atomically reserves target plus synthetic
identity, rejects a second reservation, and retains the reservation after failure.
Reuse the ledger across invocations; do not delete it to retry the public run.
This isolated certification ledger never mutates historical application evidence.

The only input identity is Avery Certification with an `example.test` email.
There are no inferred demographic, legal, authorization, consent or identity
policies. Unknown fields remain untouched and are recorded as production review
items. Uploads are not performed because they may send applicant data before final
submission. The proof can establish safe field filling while required fields remain
under review; that is not a claim of complete application readiness.

All HTTP methods except GET/HEAD and all WebSockets are blocked. A blocked write,
changed top-level board/job identity, final-submit click/form call, or security
boundary invalidates the proof. The DOM guard runs before site scripts. CAPTCHA,
login, MFA and anti-bot checks occur before filling and after filling. A detected
boundary stops the run without attempting to solve or bypass it.

Retain the entire evidence directory and ledger. `summary.json` contains the exact
HEAD, committed input hashes, synthetic inputs, concrete adapter/filler identities,
DOM actions and state, network attempts/completions, duplicate reservation evidence,
Linux child PID/start identities, browser/driver shutdown observations, trace hash,
review items and a fail-closed verdict. `trace.zip` retains Playwright sources,
snapshots and screenshots even after an ordinary fill failure. `form.html`,
`form.png` and `failure-or-final.html` provide DOM diagnostics when available.
Process-control exceptions propagate only after cleanup and summary retention.

Independent review recomputes the trace digest and all gate conditions:

```sh
PYTHONPATH=. python scripts/run_recovery_gate2.py \
  --evidence /absolute/path/to/evidence-directory --review
```

Reviewers must also compare retained input hashes with the exact Git revision,
inspect the trace, and cross-check request/DOM observations. A synthetic fixture
PASS is runner verification only. Gate 2 is PASS only with the single public run
and independently retained evidence. Missing evidence means NOT PROVEN. The owner
is not a troubleshooting resource; involve them only at a genuine human boundary.
