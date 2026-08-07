# Phase 6: Supervised Recruiter Follow-up

## Purpose

Phase 6 replaces JobTomatik's legacy automatic follow-up email path with a supervised outbound-communication boundary.

The core rule is:

> Permission to submit an application is not permission to contact a recruiter.

Application submission, recruiter outreach, and email-provider delivery are independent decisions and independent runtime gates.

## Legacy problem removed

Before Phase 6:

- `schedule_auto_followup` populated `recipient_email` with the applicant's own email address;
- the created row used status `pending`;
- Celery Beat selected every due `pending` follow-up each hour;
- no exact recipient approval was required before the provider call;
- the generic email service treated missing SendGrid configuration as mock success.

This combination made the old follow-up subsystem unsuitable for production automation.

## New state model

Follow-up delivery states:

- `draft` — editable content with no active outreach approval;
- `needs_recipient` — draft has no verified recruiter identity;
- `approved` — exact payload has active user approval;
- `sending` — durable delivery reservation committed before provider call;
- `sent` — provider accepted the approved message;
- `delivery_uncertain` — provider or worker outcome is ambiguous; automatic retry is forbidden;
- `cancelled` — closed without sending.

Approval states:

- `unapproved`
- `active`
- `revoked`
- `consumed`
- `expired`

## Independent runtime kill switch

Real recruiter email requires:

```text
ALLOW_REAL_FOLLOWUP_SEND=true
```

Default:

```text
ALLOW_REAL_FOLLOWUP_SEND=false
```

This is separate from:

```text
ALLOW_REAL_APPLICATION_SUBMIT
```

Changing application-submission controls cannot enable recruiter email.

Production or real outbound operation also requires a non-placeholder `SECRET_KEY` under the existing runtime security validator.

## Draft-only automatic preparation

The existing `auto_followup` user preference remains for backward compatibility, but its meaning is now:

> Prepare a follow-up draft after a confirmed application.

It never means:

> Automatically send an email.

`schedule_auto_followup` now:

- creates no recipient;
- creates no recruiter-contact association;
- creates no approval;
- stores `outreach_authorized=false`;
- stores status `needs_recipient`;
- records a `followup_draft_prepared` application event;
- creates an in-app reminder to select a recruiter and review the message.

Repeated scheduling is idempotent for the same automatically prepared draft.

## Exact recipient identity

A sendable follow-up requires a `RecruiterContact` that:

- belongs to the authenticated user;
- has an email address;
- matches the application company;
- has an email exactly matching `FollowUp.recipient_email`.

The applicant's own account email is always rejected as a recruiter recipient.

The API does not accept a foreign account's recruiter-contact ID.

## Exact-payload approval

Approval requires the exact phrase:

```text
APPROVE FOLLOWUP <followup_id> TO <normalized_recipient_email>
```

The approved hash binds:

- follow-up ID;
- application ID;
- user ID;
- job ID;
- job company;
- job title;
- recruiter-contact ID;
- recruiter-contact email;
- recipient email;
- subject;
- message;
- schedule;
- send idempotency key.

Any edit to recipient, contact, subject, message, or schedule revokes the old approval and clears the approved payload hash.

Approval does not require `ALLOW_REAL_FOLLOWUP_SEND=true`; an owner may review and approve while the global switch remains disabled. Delivery still cannot occur until every delivery gate passes.

## Delivery gates

Delivery requires all of:

- application status `applied` or `interviewing`;
- recorded `applied_at` timestamp;
- verified recruiter identity;
- active, unexpired exact-payload approval;
- no payload drift;
- due schedule;
- `ALLOW_REAL_FOLLOWUP_SEND=true`;
- real `SENDGRID_API_KEY` configuration;
- status `approved`.

Mock email mode is never accepted for supervised recruiter delivery.

## Reservation and duplicate prevention

The worker commits `sending` plus attempt metadata before calling the email provider.

If another worker sees:

- `sending`, it does not deliver again;
- `sent`, it returns an idempotent success without sending again.

The reservation retains:

- approval reference;
- payload hash;
- send idempotency key;
- reservation timestamp.

## Provider uncertainty

If the provider rejects the request, the provider outcome is ambiguous, or the worker crashes after reservation:

- status becomes `delivery_uncertain`;
- approval becomes `consumed`;
- `automatic_retry_allowed=false` is recorded;
- no automatic retry occurs.

The owner must inspect the provider state before creating any replacement message or approval.

## Provider success evidence

A provider-accepted delivery records:

- SendGrid response status;
- provider message ID when supplied;
- approved payload hash;
- approval reference;
- send idempotency key;
- sent timestamp;
- `supervised_followup_sent` application event;
- one outbound `RecruiterInteraction` tied to the recruiter and application;
- in-app `followup_sent` notification.

## Legacy database compatibility

Existing installations may contain old `followups` tables without Phase 6 columns.

`ensure_followup_schema` is invoked by both:

- FastAPI startup;
- Celery worker initialization.

This matters on Android, where the worker may restart independently of the API.

The compatibility upgrade:

- adds Phase 6 approval/delivery columns;
- backfills unique send-idempotency keys;
- initializes approval state to `unapproved`;
- initializes send-attempt count;
- converts legacy `pending` rows with recipients to `draft`;
- converts legacy `pending` rows without recipients to `needs_recipient`;
- installs approval/idempotency/state indexes.

No legacy `pending` row remains implicitly deliverable.

## API

Application-scoped routes:

- `POST /api/applications/{application_id}/followups`
- `GET /api/applications/{application_id}/followups`
- `PATCH /api/applications/{application_id}/followups/{followup_id}`
- `GET /api/applications/{application_id}/followups/{followup_id}/preflight`
- `POST /api/applications/{application_id}/followups/{followup_id}/approve`
- `POST /api/applications/{application_id}/followups/{followup_id}/revoke`
- `POST /api/applications/{application_id}/followups/{followup_id}/send`

All routes enforce application ownership. Recruiter-contact ownership is independently enforced.

## Follow-up Review workspace

`/followup-review` provides:

- applied/interviewing application selection;
- follow-up draft selection and creation;
- recruiter-contact selection;
- exact recipient display;
- schedule, subject, and message editing;
- preflight blocker display;
- provider configuration state;
- independent outbound kill-switch state;
- exact acknowledgment phrase;
- approval and revocation;
- supervised delivery queueing;
- attempt and delivery state.

The mobile bottom navigation remains intentionally limited to the five primary tabs. Follow-up Review is accessible from the mobile sidebar.

## Settings semantics

The previous setting label:

```text
Auto-Schedule Follow-ups
```

is replaced in the UI with:

```text
Auto-Prepare Follow-up Drafts
```

The description explicitly states that no recipient is selected and nothing is sent automatically.

## Validation contract

Phase 6 regression coverage verifies:

- applicant self-email rejection;
- exact acknowledgment requirement;
- exact payload hashing;
- mutation revocation;
- automatic draft preparation without recipient;
- independent kill-switch blocking;
- one-time successful provider delivery;
- recruiter interaction evidence;
- provider uncertainty consumes approval and prevents retry;
- legacy pending-row demotion;
- cross-account recruiter-contact rejection;
- API edit and send behavior;
- frontend routing, copy, exact-approval controls, and settings semantics;
- Compose keeps `ALLOW_REAL_FOLLOWUP_SEND=false` by default;
- verification safety manifest asserts the outbound switch is disabled by default.
