# Lever Phase A interactive handoff

This procedure runs one exact target from the frozen Day 8 corpus with JobTomatik's synthetic certification profile. It fills every safe field, pauses at an unavoidable CAPTCHA or human-verification boundary, and resumes the same retained browser to `ready_to_submit` without clicking final submit.

It does not bypass CAPTCHA, enable real submission, promote Lever maturity, or append evidence to the canonical baseline.

## Preconditions

- Run from the repository's `backend` directory.
- Use Python 3.11 and the pinned backend requirements.
- Install Playwright Chromium.
- Run inside a visible XFCE/X11 or other graphical Linux desktop session.
- Select an exact `D8-*` review ID from `backend/evidence/lever-phase-a-target-corpus/`.

```bash
cd backend
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Stage 1: run one locked target

```bash
PYTHONPATH=. python -u scripts/run_lever_phase_a_handoff.py \
  --review-id D8-001 \
  --operator TheHighBrid
```

The runner performs the following sequence:

1. Validates the complete frozen corpus and its exact SHA-256.
2. Loads exactly one active and viable target.
3. Revalidates its official Lever posting metadata and exact role identity.
4. Builds the synthetic Phase A profile and résumé.
5. Opens a visible, retained Chromium session and fills safe controls.
6. Stops at the human-verification boundary.
7. Installs final-application click and form-submit guards before operator interaction.
8. Leaves MFA and login verification forms usable while blocking the final Lever application action.
9. Allows only the CAPTCHA or human-verification step to be completed manually.
10. Verifies the challenge response and exact retained target.
11. Treats a populated reCAPTCHA, hCaptcha, or Turnstile response as completed even when its iframe remains in the page.
12. Resumes in `dry_run=True` mode and stops at `ready_to_submit`.
13. Terminates retained Chromium and deletes transient screenshot, HTML, storage-state, cookie, and log files.
14. Writes a hashed JSON report. It does not create a candidate CSV.

When Chromium appears, complete only the protected verification widget. Do not click the application submit control. Return to the terminal and press Enter. JobTomatik verifies the browser state before resuming.

The default output directory is:

```text
evidence/lever-phase-a-artifacts/<REVIEW_ID>/
```

It contains:

- `lever-phase-a-interactive-report.json`
- `lever-phase-a-synthetic-resume.pdf`

The report records the official inspection, initial handoff boundary, resumed exercise, exact adapter version, challenge verification, submit-guard state, upload evidence, frozen corpus SHA, and `final_submit_clicked=false`.

A local report is not qualifying provenance and cannot advance the count.

## Stage 2: retain the report externally

Commit one report under its exact `evidence/lever-phase-a-artifacts/<REVIEW_ID>/` path in a reviewed evidence pull request.

Each retention workflow run accepts exactly one review ID and creates exactly one artifact:

- on a pull request, it selects the single changed interactive report;
- on manual dispatch, provide one exact `review_id` input;
- multiple changed reports fail instead of sharing one artifact ID.

The `Lever Phase A interactive evidence retention` workflow validates the selected report and uploads only that review directory plus a one-record retention manifest. When the artifact is created, the workflow summary prints:

- workflow run ID;
- artifact ID;
- artifact digest;
- retained record count of `1`.

All three provenance values must come from that completed GitHub Actions run. A local SHA, locally invented run ID, URL without an artifact, or self-reference is rejected.

## Stage 3: finalize the candidate and source receipt

After the retention workflow succeeds, run:

```bash
PYTHONPATH=. python scripts/finalize_lever_phase_a_handoff.py \
  --review-id D8-001 \
  --report evidence/lever-phase-a-artifacts/D8-001/lever-phase-a-interactive-report.json \
  --workflow-run-id <GITHUB_RUN_ID> \
  --artifact-id <GITHUB_ARTIFACT_ID> \
  --artifact-digest <64_HEX_ARTIFACT_DIGEST> \
  --operator TheHighBrid
```

The finalizer requires:

- a positive numeric GitHub Actions run ID;
- a positive numeric GitHub artifact ID;
- a lowercase 64-character artifact SHA-256 digest;
- the exact GitHub Actions run URL as `source_reference`;
- a report under `evidence/lever-phase-a-artifacts/<REVIEW_ID>/`;
- the same frozen review ID inside the retained report;
- one verifier-qualified `ready_to_submit` dry run with no submission action.

It writes two review files in `evidence/`:

- `lever-phase-a-candidate-<REVIEW_ID>.csv`
- `lever-phase-a-source-<REVIEW_ID>.csv`

The source receipt uses the canonical schema:

```text
workflow_run_id,artifact_id,artifact_digest,retained_record_count
```

The finalizer writes the candidate and source receipt atomically. It does not append either row to `lever-phase-a-baseline.csv` or `lever-phase-a-sources.csv`. A separate reviewed import change must append both rows and regenerate readiness before the canonical count can advance.

## Fail-closed outcomes

The process remains nonqualifying when:

- the posting expired or official metadata changed;
- the role no longer matches the frozen corpus;
- the corpus digest changed;
- the page exposes an ambiguous required answer or unsupported control;
- the boundary is not a clean resumable CAPTCHA, MFA, login, or anti-bot challenge;
- the retained target changes;
- the challenge remains active;
- a solved CAPTCHA token is absent;
- the resumed browser does not reach `ready_to_submit`;
- the submit guard disappears or records an attempt;
- any final-submit automation log is detected;
- the report is not retained by a one-record GitHub Actions artifact;
- the workflow run ID, artifact ID, artifact digest, or report path is invalid.

Real submission, Lever supervised pilot, autopilot, and general resumable live handoffs remain disabled throughout this procedure.
