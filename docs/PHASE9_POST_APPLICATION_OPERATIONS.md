# Phase 9: Post-Application Operations

## Purpose

Phase 9 closes the loop after a verified application has been submitted or otherwise entered the user's tracked pipeline.

It adds a provenance-first operating layer for employer messages, interview preparation, offers, outcomes, and learning while preserving the existing Phase 6 recruiter-outreach approval boundary.

Phase 9 does **not** introduce a new email sender, a new application-submission path, or permission to infer consequential status changes from an inbound message.

## Product surface

`/post-application` provides three focused views:

1. **Employer inbox**
   - attach an inbound employer/recruiter message to an exact application;
   - record sender identity, source reference, subject, body preview, message hash, and received time;
   - classify the message deterministically as interview, offer, rejection, assessment, status update, application receipt, recruiter outreach, or other;
   - create or update the existing recruiter CRM contact and interaction records;
   - propose a status transition without applying it automatically;
   - require the exact user acknowledgment `CONFIRM STATUS <TARGET>` before a proposed status mutation.

2. **Interviews**
   - record a user-confirmed interview date, format, location/link, notes, and source reference;
   - move a compatible application into `interviewing` only from the explicit schedule action;
   - build an interview-preparation packet from the job requirements, active `CareerMemory`, and company `KnowledgeNode` evidence;
   - retain source references and confidence for candidate evidence;
   - never invent candidate experience when evidence is absent.

3. **Offers & outcomes**
   - record explicit `offer`, `rejected`, or `withdrawn` outcomes with source references;
   - record an offer amount when supplied;
   - compare recorded offers against the job's stored salary range and the latest existing `OpportunityEvaluation` score;
   - keep the comparison descriptive rather than choosing an offer for the user;
   - write one application-specific outcome memory with exact event provenance and `learning_scope=observed_outcome_only`.

## Safety boundaries

### Inbound classification is not permission

The deterministic message classifier is advisory. It does not mutate `Application.status`.

A classification that proposes `interviewing`, `offer`, or `rejected` requires a separate authenticated confirmation endpoint and an exact acknowledgment string. Invalid or backwards status transitions fail closed.

### Recruiter outreach remains independently supervised

Phase 9 reuses the existing recruiter CRM and Follow-Up Review surfaces. It does not call the outbound follow-up sender and it does not create or consume follow-up approvals.

Real recruiter outreach therefore still requires the Phase 6 exact-payload approval, recipient/contact checks, due schedule, real provider, and `ALLOW_REAL_FOLLOWUP_SEND=true`.

### No automatic mailbox access

Phase 9 provides an ingestion API and user-operated UI for employer messages. It does not claim access to Gmail, IMAP, Outlook, or another mailbox. A future mailbox connector must retain the same application-matching, provenance, deduplication, and no-auto-status-change invariants.

### Outcome learning is bounded

Outcome learning stores the observed result for the exact application. It does not infer broad applicant strengths, weaknesses, protected traits, or causal explanations from an offer or rejection.

## Data model

No new table or database column is required.

Phase 9 composes existing durable records:

- `Application` for current pipeline state and interview/offer fields;
- `ApplicationEvent` for inbound-message, status-confirmation, interview, and outcome provenance;
- `RecruiterContact` and `RecruiterInteraction` for CRM history;
- `CareerMemory` for bounded, source-linked outcome memory;
- `KnowledgeNode` for company context;
- `OpportunityEvaluation` for existing opportunity-fit evidence;
- `FollowUp` for read-only attention counts while outbound state remains governed by Phase 6.

## API surface

```text
GET  /api/post-application/workspace
POST /api/post-application/applications/{application_id}/messages
POST /api/post-application/applications/{application_id}/messages/{event_id}/apply-status
POST /api/post-application/applications/{application_id}/interview
GET  /api/post-application/applications/{application_id}/interview-prep
POST /api/post-application/applications/{application_id}/outcome
GET  /api/post-application/offers
```

## Classification contract

The first classifier is intentionally deterministic and inspectable. It matches a bounded phrase catalog and returns:

- `category`;
- `confidence`;
- exact `matched_phrases`;
- optional `proposed_status`;
- `requires_confirmation`;
- `classifier_version`.

It is not an AI truth oracle and does not silently modify records.

## Idempotency and account isolation

The required `source_reference` is the stable message identity for repeated manual/provider ingestion of the same application event. This protects idempotency even when `received_at` was not supplied and the server must record its own receipt time. A normalized SHA256 over sender, subject, full body, and received timestamp remains a second duplicate check for callers that use distinct source references.

Re-ingesting the same source reference for the same application returns the existing event instead of creating another CRM interaction. Distinct source references remain distinct message events. Recruiter email and company matching uses normalized literal equality rather than SQL wildcard semantics.

Every application lookup is scoped to the authenticated user. Recruiter contacts and knowledge/memory lookups are also user-scoped.

## Exit criteria

Phase 9 is complete when automated verification proves all of the following:

- inbound employer events attach only to the intended user-owned application;
- duplicate messages are idempotent even when no provider timestamp is available;
- distinct source references remain distinct message identities;
- recruiter contact matching is literal and account-scoped;
- classification never changes status by itself;
- exact confirmation is required for proposed status transitions;
- recruiter CRM interactions retain source and classification metadata;
- interview scheduling records provenance and rejects terminal application states;
- interview preparation contains only source-backed candidate evidence;
- offer comparison is descriptive and uses recorded evidence;
- outcome learning retains exact application/event provenance without unsupported generalization;
- Phase 6 follow-up approval/send state is unchanged;
- frontend routes and safety copy are present;
- full backend/browser, frontend, Android, dependency, migration, CodeQL, reproducible, and stabilization gates pass.
