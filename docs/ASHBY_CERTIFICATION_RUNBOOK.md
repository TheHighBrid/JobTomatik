# Ashby physical certification runbook

This is the final gate, not an exploratory debugging procedure.

## Preconditions

- Run current `agent/ashby-certification` on the normal JobTomatik Android/native-Chrome stack.
- Use a real Ashby-hosted role the operator genuinely intends to apply to.
- Keep the normal submission policy, Answer Vault, retained-tab recovery, and duplicate-suppression protections enabled.

## One physical run

Start the application from JobTomatik and allow the normal workflow to proceed. If JobTomatik encounters an unknown or policy-bound question, answer it through the existing Answer Vault flow. Continue the same application. A successful run must finish on genuine Ashby confirmation evidence and JobTomatik must reconcile the record to `Applied`.

## Evidence to retain

Create `evidence/ashby-real-certification.json` from the supplied example schema using facts captured by the run. The verifier must exit zero:

`python backend/scripts/verify_ashby_real_certification.py evidence/ashby-real-certification.json`

The evidence is invalid if confirmation is ambiguous, the record remains pending, the application resumed on an unrelated tab, unknown answers were guessed, or a second submission remains possible.

## Promotion

Only after the physical evidence passes may Ashby adapter metadata and `docs/ASHBY_REAL_CERTIFICATION.md` be changed to CERTIFIED. Run the Ashby adapter, handoff, confirmation, answer-policy, duplicate-suppression, and certification-contract regression suites before merge.
