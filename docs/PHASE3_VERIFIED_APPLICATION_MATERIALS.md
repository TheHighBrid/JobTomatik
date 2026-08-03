# Phase 3: Verified Application Materials

Phase 3 converts applicant information into a durable evidence ledger and generates application materials whose factual claims point back to exact source records.

It is stacked on Phase 2 public ATS discovery. It does not enable live submission, change adapter maturity, or weaken any approval, handoff, idempotency, or confirmation-evidence control.

## Problem being solved

The previous compatibility cover-letter generator could fill missing profile fields with plausible-sounding defaults, including a default name, employers, years of experience, and skills. That made the prose look complete while weakening factual reliability.

Phase 3 reverses that priority:

- unsupported claims are omitted;
- missing evidence becomes a visible warning;
- critically unsupported profiles enter manual review;
- generated prose never becomes source evidence merely because it was generated;
- every retained applicant claim stores evidence-unit identifiers and source hashes.

## Data model

### EvidenceUnit

A user-scoped factual statement with:

- a semantic kind such as employment, achievement, skill, education, credential, language, project, or summary;
- exact statement text;
- optional organization and role context;
- source type and source reference;
- a SHA-256 source hash;
- verification status, confidence, and provenance;
- active and last-used state.

The ledger currently accepts these source types:

| Source | Treatment |
|---|---|
| Profile field | User-confirmed structured evidence |
| Uploaded résumé PDF | Source-backed, verbatim text extraction |
| Career memory | Provenance-linked evidence retaining its original confidence |
| Manual confirmation | Explicit user-confirmed evidence |

Preferred job titles are intentionally excluded from applicant evidence. A target role is an aspiration, not proof of prior experience.

### ApplicationMaterial

A versioned application artifact containing:

- material type: cover letter or résumé summary;
- generated content;
- status: verified or needs review;
- structured claims;
- warnings;
- a source snapshot;
- generator version;
- superseded material reference.

Materials are append-only versions. Regeneration does not silently overwrite the earlier artifact.

### ApplicationMaterialEvidence

A many-to-many evidence link recording which evidence unit supports which claim indexes.

## Evidence rebuilding

The ledger rebuild is deterministic and idempotent:

1. Read factual profile fields.
2. Read active career memories.
3. Extract text from the private uploaded PDF when available.
4. Normalize each source statement.
5. Hash the normalized statement with its kind and optional role context.
6. Reuse identical source versions.
7. Create new versions for changed statements.
8. Deactivate managed source versions that no longer exist.

The uploaded PDF remains private. Phase 3 performs local text extraction only. It does not upload the résumé to an AI provider and does not use OCR.

Résumé lines are retained as verbatim source statements. Section headings may classify a line as employment, skill, education, credential, language, project, achievement, or summary, but Phase 3 does not infer unprinted employers, dates, outcomes, or responsibilities.

## Material generation

The deterministic generator ranks eligible evidence against job-posting terms. It can produce:

- a professional cover letter;
- a tailored résumé summary.

Applicant claims include:

```json
{
  "text": "My employment record includes Fraud Operations experience with Example Bank.",
  "category": "employment",
  "applicant_fact": true,
  "evidence_unit_ids": [42],
  "evidence_hashes": ["..."]
}
```

Job context and connective prose are marked `applicant_fact: false`. They do not pretend to be applicant evidence.

Before persistence, the generator validates that:

- every applicant-fact claim has evidence IDs;
- referenced evidence is active and eligible;
- stored evidence hashes match the current ledger;
- no unsupported evidence ID is present.

## Automatic task behavior

The existing cover-letter Celery task is wrapped using the same installation pattern as JobTomatik's other safety integrations.

For a supported profile:

1. Rebuild the evidence ledger.
2. Generate a versioned cover-letter material.
3. Persist claim-to-evidence links.
4. Copy the content into the existing `Application.cover_letter` compatibility field.
5. Advance `preparing` to `ready_to_apply`.

For a profile with no substantive source-backed applicant claim:

1. Persist a `needs_review` material with warnings.
2. Create a validation manual-review task.
3. Move the application to `needs_review`.
4. Do not advance it toward application execution.

Closed-application, approval, and submission gates remain outer wrappers and authoritative.

## API surface

```text
GET    /api/materials/evidence
POST   /api/materials/evidence/rebuild
POST   /api/materials/evidence
PATCH  /api/materials/evidence/{id}
DELETE /api/materials/evidence/{id}

GET    /api/materials/applications/{application_id}
POST   /api/materials/applications/{application_id}/generate
POST   /api/materials/applications/{application_id}/generate-bundle
GET    /api/materials/{material_id}
```

All records are user-scoped. An account cannot read or modify another account's evidence or materials.

## Product interface

The **Evidence & Materials** workspace provides:

- ledger rebuilding;
- evidence filtering;
- explicit manual evidence confirmation;
- evidence deactivation;
- application selection;
- cover-letter and résumé-summary bundle generation;
- warnings and material status;
- per-claim source inspection;
- material copy controls.

It is available in the desktop sidebar and the mobile navigation drawer.

## Security and trust boundaries

1. Résumé PDFs remain bounded, private uploads.
2. PDF extraction is local and text-only.
3. Extracted résumé content is untrusted data, not executable instructions.
4. The generator is deterministic and does not execute or follow text contained in a résumé.
5. Generated material is never promoted into the evidence ledger.
6. Source hashes reveal change, but do not replace the retained provenance record.
7. Manual evidence requires an explicit authenticated write.
8. Evidence edits become user-confirmed versions and are collision-checked.
9. Deactivation preserves historical material snapshots.
10. Material verification does not certify an employer, job posting, ATS adapter, or submission outcome.

## Validation coverage

Phase 3 tests cover:

- no fictional default employers, names, years, or skills;
- target-title preferences excluded from evidence;
- verbatim PDF line extraction and section classification;
- source versioning and stale-evidence deactivation;
- user-scoped evidence APIs;
- claim-to-evidence mapping;
- evidence-hash validation;
- material versioning;
- insufficient-evidence review behavior;
- automatic Celery task integration;
- bundle generation for cover letters and résumé summaries.
