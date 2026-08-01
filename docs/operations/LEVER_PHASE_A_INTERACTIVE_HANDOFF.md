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

## Run one locked target

```bash
PYTHONPATH=. python -u scripts/run_lever_phase_a_handoff.py \
  --review-id D8-001 \
  --operator TheHighBrid
```

The runner performs the following sequence:

1. Loads exactly one active and viable target from the frozen corpus.
2. Revalidates its official Lever posting metadata and exact role identity.
3. Builds the synthetic Phase A profile and résumé.
4. Opens a visible, retained Chromium session and fills safe controls.
5. Stops at the human-verification boundary.
6. Installs capturing click and form-submit guards before operator interaction.
7. Allows only the CAPTCHA or human-verification step to be completed manually.
8. Verifies the challenge response and exact retained target.
9. Resumes in `dry_run=True` mode and stops at `ready_to_submit`.
10. Terminates retained Chromium and writes a hashed JSON report plus candidate CSV.

When Chromium appears, complete only the protected verification widget. Do not click the application submit control. Return to the terminal and press Enter. JobTomatik verifies the browser state before resuming.

## Outputs

The default output directory is:

```text
evidence/lever-phase-a-interactive/<REVIEW_ID>/
```

It contains:

- `lever-phase-a-interactive-report.json`
- `lever-phase-a-candidate.csv`
- `lever-phase-a-synthetic-resume.pdf`

The report records the official inspection, initial handoff boundary, resumed exercise, exact adapter version, challenge verification, submit-guard state, upload evidence, and `final_submit_clicked=false`.

The candidate uses the report SHA-256 as its immutable local source reference. The command never edits `evidence/lever-phase-a-baseline.csv`; a separate evidence review and import change is required before the canonical count can advance.

## Fail-closed outcomes

The command exits without a qualifying candidate when:

- the posting expired or official metadata changed;
- the role no longer matches the frozen corpus;
- the page exposes an ambiguous required answer or unsupported control;
- the boundary is not a clean resumable CAPTCHA, MFA, login, or anti-bot challenge;
- the retained target changes;
- the challenge remains active;
- the resumed browser does not reach `ready_to_submit`;
- any final-submit click is detected.

Real submission, Lever supervised pilot, autopilot, and general resumable live handoffs remain disabled throughout this procedure.
