# Costs and infrastructure

**As of:** 2026-10-16. Amounts are CAD unless an invoice says otherwise. Unknown amounts are not zero.

## Current machine

| Item | Last available observation | Evidence confidence |
|---|---|---|
| Provider | Existing OVHcloud VPS | Fresh authorized host inspection, 2026-10-16 14:46 UTC |
| Host identity | `vps-10618f0e` | Recorded deployment and Desktop Commander inventory |
| OS / architecture | Ubuntu 26.04.1 LTS, x86_64 | Fresh /etc/os-release and uname observation |
| RAM | 7,746 MiB total; 6,349 MiB available at inspection; no swap | Fresh free -m observation; transient availability |
| Root disk | df -h: 72G total, 17G used, 56G available | Fresh OS-reported filesystem values, rounded |
| CPU | 4 virtual CPUs; guest model Intel Core Processor (Haswell, no TSX); KVM | Fresh lscpu; virtual guest identity, not physical-host attestation |
| Docker / Git | Installed and used during this refresh | Fresh inspection and isolated test/image builds |
| Administration | Desktop Commander online and operational | Fresh connector inventory and host commands |
| Client | Android phone/tablet or web browser | Thin client; does not host the production browser |

These are timestamped guest-OS observations, not a provider plan specification, performance benchmark or physical-host attestation. Available memory and disk change with workload and image/evidence growth. Do not infer the VPS plan or price from these figures.

## Production topology

The supported configuration is [docker-compose.onehost-production.yml](../docker-compose.onehost-production.yml): FastAPI, PostgreSQL 15, Redis 7 and one Celery worker with solo pool/concurrency 1. Playwright owns persistent Chromium. API and worker share the network/PID namespace, browser node identity, persistent `/state` and private display socket. Beat is absent.

See [deployment instructions](operations/ONEHOST_PRODUCTION_DEPLOYMENT.md) for exact commands, stable secrets, TLS ingress and safe defaults. SQLite and historical Android/PRoot execution are not the supported production database/runtime.

| Toolchain | Repository pin |
|---|---|
| Python | 3.11 |
| Node | 20, minimum 20.19.0 |
| Java | 21 |
| Gradle | 9.5.1 |
| Android Gradle plugin | 8.13.2 |
| Android build API | 35 |

Source: [.jobtomatik-toolchain.env](../.jobtomatik-toolchain.env). Pins describe the build contract, not proof of the host's installed versions.

## Actual cost ledger

| Cost item | Current verified amount | Billing status / missing evidence |
|---|---|---|
| OVH VPS | Unknown | Invoice, plan, billing term, renewal and currency not available |
| Backup / snapshots | Unknown | Snapshot existence is reported; provider billing and retention cost not verified |
| AI API usage | Unknown | Template is Compose default; actual optional-provider usage/spend not available |
| Email / external notifications | Unknown | Optional provider settings exist; paid tier/usage not established |
| GitHub / CI / artifact storage | Unknown | Public repository confirmed; actual account usage and billed extras not available |
| Domain / ingress / monitoring | Unknown | Existing provider hostname observed; separate paid services not established |
| Historical cloud trials and credits | Incomplete | Prior trial credit is not an invoice or current balance |
| This documentation refresh | No new paid resource or subscription created | Does not quantify existing account or AI subscription charges |

**Current monthly total: not verified. Historical cumulative total: not verified.** No billing-account evidence was available to calculate either. There is no substantiated claim that the whole system currently costs $0.

The next cost update should read existing invoices and usage records through authorized access. It should not require a purchase, provider migration or a guessed VPS price.

## Future total-cost model

Use a consistent currency and billing period. Let:

- `H` = monthly-equivalent host invoice, including its renewal price;
- `B` = backups, snapshots and off-host storage;
- `A` = metered AI API usage;
- `E` = email and notification services;
- `G` = billed CI, artifacts and repository services;
- `D` = domain and ingress allocation;
- `T` = applicable taxes and currency-conversion fees;
- `C` = applicable credits, allocated once rather than repeated after expiry.

**Recurring monthly total = H + B + A + E + G + D + T - C.**

**First-year cash total = setup purchases + actual invoices across 12 months + usage + taxes/fees - actual credits.** Use renewal pricing for months outside a promotion and allocate annual purchases once. Hardware already owned and optional personal AI subscriptions should be shown separately from incremental hosting cost.

| Future scenario | Cost expectation | Trigger |
|---|---|---|
| Existing OVH OneHost, template provider | Existing host plus verified backup/operations charges | Baseline; no second server required by architecture |
| Same host with metered AI/email | Baseline plus actual API/message usage | Owner-approved quality or communication need |
| Larger VPS | New renewal invoice plus migration/overlap cost if any | Measured resource pressure, not a theoretical browser-size rule |
| Managed database / multiple workers | New infrastructure and operational costs; not presently required | A separately justified scaling design and owner budget |
| Provider migration | Temporary overlap, transfer/backup and new host charges | Demonstrated reliability, access or price problem |

**Future exact monthly/yearly total remains unpriced until invoices and intended usage are known.** No new paid commitment or spending ceiling is authorized by this document.

## Resource and recovery evidence still needed

- Persistent-volume and evidence-directory usage with timestamps; guest CPU/OS/RAM/root-disk observations are now recorded above.
- Browser/API/worker memory under the actual supported workflow, including retained sessions.
- Evidence growth, retention limits, free-disk alarms and backup storage usage.
- An isolated restore and rollback result bound to source/image identity.
- Invoice amount, currency, tax, billing term, renewal date and all optional-service usage.

Record redacted facts only. Never commit invoice payment details, secrets, personal applications or browser profiles.
