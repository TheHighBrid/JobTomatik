# Answer Policy Vault Readiness Contract

## Purpose

JobTomatik may use an application answer automatically only when the value is encrypted, current, conflict-free, attributable to a known source, confirmed by the authenticated user, and explicitly authorized for autofill.

The readiness report is conservative. Its country and platform profiles are the minimum policy coverage required by JobTomatik before unattended execution. They are not claims that every employer asks every listed question. Any unknown required question still stops for review.

## Trust metadata

Every answer policy records:

- `provenance`: `user_provided`, `verified_import`, `ai_suggested`, or `unknown`;
- `confidence`: a value from `0.0` to `1.0`;
- `confirmed_at`: the user-confirmation timestamp;
- `consent_metadata`: how and when automatic use was authorized;
- `source_metadata`: non-secret context identifying the reviewed source;
- `expires_at`: the optional review deadline;
- `version`: incremented whenever the record changes.

Primary answers, display labels, and fallback options remain encrypted at rest. The readiness report exposes policy IDs and trust metadata, not the stored answer values.

## Automatic-use invariants

A policy cannot autofill when any of the following is true:

1. It is inactive.
2. Its mode is `ask_each_time` or `skip`.
3. It has expired.
4. Its encrypted value cannot be verified.
5. Its provenance is unknown.
6. Its confidence is below `0.80`.
7. It is not confirmed.
8. Its consent record does not authorize autofill.
9. Autofill is disabled.
10. It contains no usable approved answer.
11. Another matching policy at the same scope priority contradicts it.

AI suggestions are ordinary untrusted proposals until the user reviews and confirms them. No default, catalog suggestion, profile inference, or model output becomes an approved answer by itself.

## Scope resolution

Scope priority is:

1. company;
2. platform/domain;
3. global.

A more specific policy may intentionally override a global policy. Two contradictory policies at the same priority are a hard conflict. Runtime execution and readiness reporting both stop rather than selecting a row by database order.

## Minimum applicant profile

The current unattended-readiness contract requires:

- full name;
- email;
- phone number;
- location or mailing address;
- current resume.

## Country profiles

Canada, the United States, the United Kingdom, and the generic fallback profile require reviewed policies for:

- legal work authorization;
- current or future sponsorship requirement.

Citizenship, residency, demographic identity, disability, veteran status, criminal history, and other protected or sensitive disclosures are not inferred and are not required merely to make the readiness score green.

## Platform profiles

The minimum platform coverage is:

| Platform | Required decision policies |
| --- | --- |
| Greenhouse | application declaration/terms; applicant-data processing |
| Lever | application declaration/terms |
| Ashby | application declaration/terms; applicant-data processing |
| Generic | application declaration/terms |

These policies represent an approved decision, including an approved decline where the form permits it. Employer-specific or changed terms can still trigger review.

## Readiness endpoint

Authenticated endpoint:

```text
GET /api/profile/answer-policies/readiness
```

Optional query parameters:

- `country_code`, default `CA`;
- `platform`, one of `greenhouse`, `lever`, `ashby`, or `generic`;
- `target_url`, used to detect platform and match scoped policies;
- `company`, used to match company-scoped policies.

The response contains:

- a completeness score;
- exact missing profile fields;
- required policy statuses;
- blocker codes and policy IDs;
- overlapping conflicts;
- a boolean `ready_for_unattended` result;
- explicit no-inference guarantees.

The Settings screen renders this report above the Answer Policy Vault.

## Editing and expiry behavior

Changing an answer, fallback, scope, mode, provenance, confidence, source metadata, or expiry revokes confirmation and autofill unless the same authenticated request explicitly reconfirms the revised record. Expired policies remain visible for repair but cannot be used automatically.

## Failure behavior

Every failure is fail-closed:

- missing policy: manual review;
- unknown question: manual review;
- conflict: manual review;
- corrupt ciphertext: manual review;
- expired consent or answer: manual review;
- low-confidence or unknown provenance: manual review.

No blocker is converted into a guessed answer.
