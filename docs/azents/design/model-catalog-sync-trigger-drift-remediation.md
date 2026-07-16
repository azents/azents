---
title: "Model Catalog Sync Trigger Drift Remediation"
created: 2026-07-16
updated: 2026-07-16
implemented: 2026-07-16
tags: [backend, frontend, api, testing]
---

# Model Catalog Sync Trigger Drift Remediation

## Context

ADR-0067 defines integration model catalog synchronization as an explicit, throttled lifecycle. The initial implementation eventually added create/update background sync, manual sync, and a latest-running-attempt check, but it did not complete the lifecycle described by ADR-0067-D5, ADR-0067-D17, and `model-catalog-projection-sync.md` REQ-3.

This remediation preserves the stored-projection read contract while completing the missing trigger, throttling, retry, and UI behavior. ADR-0067 remains immutable and authoritative.

## Source Requirements

The accepted lifecycle requires:

- best-effort initial sync after integration creation;
- sync after credential or catalog-affecting configuration changes;
- explicit user sync from the integration/model-picker UI;
- optional lazy refresh when a stale integration catalog is actively viewed;
- integration- and workspace-scoped throttling;
- duplicate-running prevention;
- automatic retry suppression after credential/configuration failures;
- transient-provider backoff;
- no global cron over customer integration catalogs;
- create/update responses to remain independent from background sync success.

## Drift Register

| Drift | Previous behavior | Required correction |
| --- | --- | --- |
| Update trigger scope | Every successful PATCH queued sync, including name-only and disable operations | Queue only for credential/config changes and re-enabling |
| Stale refresh | Stored reads never requested refresh | Return stored data first, then queue a best-effort stale refresh |
| Integration throttle | Sequential explicit requests could call the provider without a cooldown | Enforce an integration cooldown before explicit/stale sync |
| Workspace throttle | Different integrations could start provider listing bursts in one workspace | Enforce a workspace-wide start cooldown |
| Transient backoff | Failure diagnostics mentioned retry policy but no policy evaluated them | Classify retryable provider failures and enforce backoff |
| Credential failure suppression | Diagnostics recorded a block marker, but no automatic trigger consumed it | Block stale automatic retry until explicit retry or configuration change |
| Duplicate claim | Latest-attempt check and write were separate, unlocked operations | Lock workspace and catalog rows before evaluating policy and creating an attempt |
| Stuck running attempt | A crashed task could leave the catalog permanently blocked | Expire and recover running attempts after a bounded lease |
| Picker state | Button state ignored mutation progress and throttle time | Disable for local pending, running, and server-provided retry time |
| Test trigger | Deterministic E2E integrations skipped automatic create sync | Use deterministic integrations to verify create/update triggers |

## Remediation Design

### Trigger model

Every integration sync request carries one of four reasons:

- `create` — enabled integration creation or successful OAuth connection;
- `config_update` — credential/config change or re-enable;
- `explicit` — user-selected sync/retry;
- `stale_refresh` — lazy refresh after a stored catalog read reports stale data.

Creation and configuration-change triggers bypass cooldown and failure backoff because they represent new provider state. They still cannot replace an active attempt. Name-only updates and disable operations do not sync.

Explicit requests bypass the credential-failure automatic block but respect integration/workspace cooldown and transient backoff. Stale refresh respects every policy guard.

### Policy windows

The initial operational policy uses fixed service constants:

| Policy | Window |
| --- | ---: |
| Catalog stale threshold | 15 minutes |
| Integration explicit/stale cooldown | 30 seconds |
| Workspace explicit/stale cooldown | 5 seconds |
| Transient-provider failure backoff | 5 minutes |
| Running-attempt lease | 15 minutes |

These values are operational tuning parameters, not durable data contracts. They can move to deployment settings if production evidence requires environment-specific tuning.

### Atomic attempt claim

Attempt start is serialized in one database transaction:

1. lock the workspace row;
2. lock the catalog row;
3. read the latest catalog and workspace integration attempts;
4. evaluate running, cooldown, backoff, automatic-block, and stale policy;
5. recover an expired running attempt when necessary;
6. create the new running attempt and update `latest_attempt_id`.

The locks make the check-and-create operation atomic without adding a new lease table or holding a database transaction during provider network calls. Completion locks the catalog again and publishes only if the completing attempt is still `latest_attempt_id`; this fences an expired worker that resumes after a replacement attempt has started.

### Failure classification

Provider listing adapters classify failures into two policy groups:

- credential/configuration/permission failures set `automatic_retry_blocked=true` and require explicit retry or configuration change;
- transport, rate-limit, provider 5xx, and invalid-provider-response failures remain automatically retryable after backoff.

Unexpected catalog service failures mark the claimed attempt failed before propagating. A crashed process can still leave a running attempt, so the running lease provides eventual recovery.

### Stored read and lazy refresh

Catalog entry GET continues to read stored projections only. Its response adds:

- catalog scope;
- stale state;
- earliest explicit sync time;
- automatic-retry-blocked state.

After producing the stored response, the route queues stale refresh only for integration-scoped catalogs. The sync policy rechecks staleness and all throttle/backoff state atomically before provider work begins.

### Picker behavior

The picker:

- disables sync while the local mutation is pending;
- disables sync while the latest attempt is running;
- disables sync until the server-provided retry time;
- shows stale automatic-refresh and throttle state;
- polls while a stale automatic refresh is eligible or an attempt is running;
- stops automatic polling when credential/configuration failure blocks retry.

## Non-goals

- No global cron for integration catalogs.
- No durable generic job queue is introduced.
- No catalog snapshot or attempt-history redesign is included.
- System catalog scheduling remains separate.
- Policy windows are not exposed as public configuration in this remediation.

## Test Strategy

Product behavior remains E2E-primary, with policy and repository tests providing deterministic boundary coverage.

### E2E validation matrix

| Behavior | Verification | Expected result |
| --- | --- | --- |
| Create trigger | Create deterministic integration and wait on stored catalog state | Initial attempt completes without explicit sync POST |
| Update trigger scope | Apply name-only update, then credential update | Name keeps attempt ID; credential update creates a new successful attempt |
| Explicit throttle | POST sync immediately after initial sync | HTTP 429 with `Retry-After` |
| Stored read | Read catalog while sync lifecycle is active | Read returns stored state without provider dependency |

### Backend validation

- Pure policy tests cover stale threshold, integration/workspace cooldown, transient backoff, credential block, running conflict, and expired-running recovery.
- Repository tests cover serialized attempt claims and persisted cooldown decisions when PostgreSQL is available.
- Route tests cover create/config/stale enqueue conditions and deterministic E2E trigger support.
- Provider adapter tests cover credential versus transient failure classification.

### Frontend validation

- Format, lint, and typecheck cover generated response fields, picker polling, pending state, and localized copy.
- Existing picker stories remain the visual regression surface for picker state rendering.

### Environment and skip policy

Deterministic E2E requires the standard Azents E2E devserver/database fixtures and no live provider credential. Local repository tests may skip when Docker/PostgreSQL is unavailable; deterministic CI must execute them. Live Bedrock, Vertex, and ChatGPT OAuth verification remains optional because the policy boundary is provider-independent and provider credentials are external prerequisites.
