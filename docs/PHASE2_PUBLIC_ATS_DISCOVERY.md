# Phase 2: Public ATS Discovery and Deterministic Evaluation

## Purpose

Phase 2 connects JobTomatik's existing discovery workflow to official public Greenhouse, Lever, and Ashby job-board APIs, then turns every accepted result into explainable, user-scoped intelligence.

The discovery layer is read-only. It does not open application forms, create applicant sessions, bypass human-verification boundaries, promote adapter maturity, or submit applications.

## Supported official sources

JobTomatik supports explicitly configured targets for:

| Provider | Official endpoint pattern | Target identifier |
| --- | --- | --- |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{identifier}/jobs` | board token |
| Lever | `api.lever.co/v0/postings/{identifier}` | site name |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{identifier}` | job-board name |

Identifiers may contain letters, numbers, underscores, and hyphens only. JobTomatik does not discover arbitrary tenants or crawl provider directories.

## Configuration

The Profile page stores official board targets under `job_preferences.ats_targets`.

```text
greenhouse:example-bank|Example Bank
lever:example-fintech|Example Fintech
ashby:example-org|Example Organization
```

Each line contains:

```text
provider:identifier|Optional Company Label
```

The Job Discovery page can also accept one-off targets. Its provider-specific inputs use:

```text
identifier|Optional Company Label
```

## API request

`POST /api/jobs/search`

```json
{
  "keywords": "fraud investigator AML",
  "location": "Ottawa",
  "salary_min": 75000,
  "sources": ["greenhouse", "lever"],
  "ats_targets": [
    {
      "provider": "greenhouse",
      "identifier": "example-bank",
      "company": "Example Bank"
    },
    {
      "provider": "lever",
      "identifier": "example-fintech",
      "company": "Example Fintech"
    }
  ],
  "limit": 50
}
```

An omitted `sources` field uses the existing broad defaults. An explicitly empty source list searches nothing.

## Normalized job contract

Official results enter the existing `Job` model with namespaced external IDs:

```text
greenhouse:{identifier}:{provider_job_id}
lever:{identifier}:{provider_job_id}
ashby:{identifier}:{provider_job_id}
```

`raw_data` retains:

- official-provider provenance;
- provider and tenant identifier;
- provider API URL;
- provider job ID;
- selected public application URL;
- normalized application method;
- bounded provider metadata;
- deterministic scoring evidence.

Provider responses are limited to 10 MB and must contain valid JSON in the expected shape.

## Deterministic scoring

The scorer produces a 0 to 100 score and a normalized 0 to 1 score without requiring an LLM.

Signals include:

- preferred titles;
- preferred skills;
- search terms;
- explicit weighted terms;
- title versus body placement;
- preferred locations and remote status;
- minimum salary;
- high-confidence career-memory matches;
- excluded phrases;
- company and title blocklists.

Every result records the terms that matched, where they matched, their point contribution, location and salary adjustments, exclusions, blockers, memory references, and scoring version.

Company and title blocklists are hard blockers and prevent persistence. Excluded phrases reduce the score but do not masquerade as hard blockers.

## Intelligence ingestion

For every accepted discovery result, JobTomatik:

1. tags skills, seniority, and industry;
2. computes deterministic relevance;
3. deduplicates by namespaced external ID;
4. persists the global job row when new;
5. creates a user-scoped ten-dimension opportunity evaluation;
6. stores A-G analysis evidence and the source snapshot;
7. creates or updates user-scoped company and role knowledge nodes;
8. links the company to the role with a `hires_for` edge;
9. marks verified career memories used by the score;
10. records and completes an inspectable discovery AgentRun.

A globally deduplicated job can still produce separate evaluations and graph context for multiple users. One account's preferences, memories, or evaluation cannot replace another account's records.

## Legitimacy handling

A job fetched directly from an explicitly configured official public ATS API receives:

```text
legitimacy_status = likely_legitimate
```

This means the listing came from the configured provider endpoint. It is not a guarantee about the employer, role quality, future availability, compensation, or hiring intent.

Broad scraped sources retain `unknown` legitimacy until separately researched.

## Submission boundary

Discovery provenance does not authorize application execution.

The existing unattended policy remains authoritative and still requires:

- an explicitly enabled platform;
- canonical adapter maturity;
- user-level autonomy approval;
- application caps and quiet-hour compliance;
- known job attributes;
- employer, location, language, salary, and sponsorship policy compliance;
- existing idempotency, approval, handoff, and confirmation-evidence controls.

Greenhouse, Lever, and Ashby discovery support therefore cannot promote their application adapters or enable live submission.

## Database compatibility

`JobSource` now includes `greenhouse`, `lever`, and `ashby`.

SQLite accepts the new values through the model definition. Existing PostgreSQL deployments receive additive values through the startup compatibility migration using:

```sql
ALTER TYPE jobsource ADD VALUE IF NOT EXISTS ...
```

The enum update uses an autocommit connection because PostgreSQL enum additions cannot safely share the ordinary transactional migration path on all supported versions.

## Provenance and licensing

This implementation is independently authored for JobTomatik. It adapts architectural concepts from the repository owner's JobSniffing project, including explicit official-board targeting, bounded JSON fetching, provider normalization, and deterministic local scoring.

No JobOps or AIHawk implementation, assets, or styling were copied into this phase.
