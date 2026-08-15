# Final-Day No-Submit Application Preparation Handoff

This runbook prepares an **exact, owner-selected application** for review. Its permitted outcome is a locally generated, source-linked material bundle that the owner has inspected. It must not open an external application form, issue an approval, queue a submission attempt, send recruiter outreach, or click final submit.

## Required owner input

Before any candidate is prepared, record the exact candidate identifier shown in the Lever Day 16 workspace, the official application URL, and the owner’s explicit selection to prepare **only** that candidate. A readable owner résumé and truthful approved-profile data are required. Do not infer legal, work-authorization, demographic, disability, veteran, salary, or consent answers.

| Input | Must be available before preparation |
|---|---|
| Exact candidate | Review ID, role, employer, and official Lever URL |
| Owner selection | Explicit permission to prepare materials for that one candidate |
| Résumé | Current, readable owner résumé attached to the account |
| Source claims | Every statement in the materials traceable to owner-provided or official-posting evidence |
| Runtime state | The intended runtime reports no-submit controls as disabled |

## Permitted workflow

1. Start from the **Lever Day 16 launch candidates** panel in the application.
2. Confirm the role, employer, official posting URL, and review ID match the owner-selected candidate.
3. Select **Prepare real material bundle**. If a current bundle exists but the posting or résumé changed, select **Refresh real material bundle** instead.
4. Open **Evidence & Materials** for the resulting application record.
5. Read the latest cover letter and résumé summary in full. Review every linked source claim and either approve or reject each material according to the owner’s truthful record.
6. Record the material versions, dossier hash, Phase A source hash, review outcome, unresolved blockers, and the exact runtime revision in the handoff receipt.

Preparation refreshes official posting metadata and creates source-linked local materials. It does not open a form, issue or consume an approval, queue work, or submit an application.

## Stop boundaries

Stop after material review. The following actions are intentionally outside this handoff:

- **Open fresh preflight**: a separate later step that requires the official form and exact payload to be revalidated.
- **Create or inspect an active approval**: approval is short-lived and must be bound to a fresh, exact payload.
- **Submit**: requires explicit per-application authorization after a fresh preflight; a submit click alone never proves confirmation.
- **CAPTCHA, MFA, login, identity, or assessment actions**: the owner must handle any required third-party step personally.
- **Outreach or follow-up sending**: separate authorization is required and is not implied by material review.

If the workspace shows **Ready for fresh preflight**, that means local preparation and review are complete. It does **not** mean the current live form or exact payload has passed preflight, and it is not permission to submit.

## Required handoff receipt

Use the following receipt after each prepared candidate.

```text
Candidate review ID:
Employer and role:
Official application URL:
Owner selection recorded:
Runtime revision:
Dossier SHA-256:
Phase A source SHA-256:
Cover-letter version and review result:
Résumé-summary version and review result:
Claim sources inspected:
Open review blockers:
No-submit boundary preserved: yes/no
External form opened: no
Approval issued or consumed: no
Submission attempt queued: no
Final-submit click: no
Outreach sent: no
Recommended next action:
```

The next action may be **resolve a source/material blocker**, **refresh materials because inputs changed**, or **request the owner’s separate authorization for a fresh preflight**. It must never be inferred from this preparation record.

## References

- `frontend/src/components/LeverPhaseBLaunchPanel.jsx`
- `docs/operations/lever-phase-b-dossier.md`
- `docs/architecture/APPLICATION_STATE_MODEL.md`
- `docs/operations/FINAL_DAY_ANDROID_RUNTIME_HANDOFF.md`
