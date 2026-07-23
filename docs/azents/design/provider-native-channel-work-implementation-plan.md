---
title: "Provider-Native Channel Work Progress Implementation Plan"
created: 2026-07-23
updated: 2026-07-23
tags: [external-channel, activity, slack, implementation, testing]
document_role: supporting
document_type: supporting-plan
---

# Provider-Native Channel Work Progress Implementation Plan

## Feature Baseline

- Requirements: [`work-260723/REQ`](../requirements/work-260723-provider-native-progress.md)
- ADR: [`work-260723/ADR`](../adr/work-260723-provider-native-progress.md)
- Design: [`work-260723/DESIGN`](work-260723-provider-native-progress.md)
- Stack prefix: `Provider-native Channel Work`

The feature adds a provider-neutral Channel Work title and rich task semantics, then renders that canonical state through Slack's native Plan and task presentation while preserving the existing complete-snapshot, retained-message, recovery, and at-most-once delivery contracts.

## Delivery Shape

### PR 1 — Design baseline and implementation plan

Establish the confirmed Requirements, accepted ADR decisions, primary Design, and this temporary phased plan. No product behavior changes.

### PR 2 — Backend canonical work and Slack presentation

Implement the provider-neutral title, rich task/source models, failed task status, version-2 desired snapshot, database migration, `channel_action` contract and prompt guidance, Slack complete-snapshot adapter, recovery integration, and focused backend tests.

Dependencies: PR 1.

Validation:

- migration upgrade/downgrade tests;
- canonical model and action validation tests;
- exact Slack checking and Plan payload tests;
- work repository idempotency, recovery, and lifecycle tests;
- Ruff, Pyright, and focused Pytest.

### PR 3 — Management contracts, clients, UI, and deterministic E2E

Expose typed canonical work title/tasks through the management API, regenerate public OpenAPI clients, update Session Channels presentation and stories, extend the deterministic Slack fake and External Channel E2E to verify the full invocation-to-Plan journey, and add Web Surface coverage.

Dependencies: PR 2.

Validation:

- OpenAPI generation and generated-client checks;
- management route/repository tests;
- frontend stories and component behavior;
- deterministic External Channel E2E;
- Web Surface E2E;
- TypeScript format, lint, typecheck, and build run sequentially.

### PR 4 — Validation, spec promotion, and cleanup

Run the full planned verification matrix, fix integration defects, compare the implementation against current specs, update living specs, add implemented dates to the Requirements and Design after successful verification, and remove this temporary implementation plan.

Dependencies: PR 3.

Validation:

- full required repository CI matrix;
- focused backend and frontend suites after any fixes;
- deterministic and Web Surface E2E evidence;
- spec review and documentation validation.

## Primary E2E Validation Matrix

| User-visible behavior | Required evidence |
| --- | --- |
| Invocation immediately creates checking progress | Slack fake captured create request before Agent work update |
| Agent supplies localized progressive work title | Deterministic scripted `channel_action` and captured Plan title |
| Task status/details/output/sources render natively | Exact Slack Plan task payload assertions |
| Same Tracker receives complete latest snapshot | Stable provider message identity plus captured update request |
| Canonical state is provider-neutral | Public management projection contains title and typed semantic tasks, not Slack blocks |
| Failed task is distinct from provider delivery failure | Management API/UI and Slack task status assertions |
| Session Channels remains usable on mobile | Browser assertion at mobile viewport |
| Recovery uses latest desired snapshot | Backend integration replacement/catch-up assertions |

## Fixture and Prerequisite Support

The existing credential-free Slack provider fake and public API journey are the primary substrate. Extend the fake only to retain complete request bodies needed for assertions. Add a deterministic scripted model response capable of calling `channel_action`; do not write product state directly through test database access.

No live Slack credentials are required for mandatory verification. Optional live verification follows the repository live-external policy and must include a clickable Slack conversation link.

## Spec Impact Candidates

- `docs/azents/spec/domain/external-channel.md`
- `docs/azents/spec/flow/external-channel-delivery.md`
- `docs/azents/spec/domain/toolkit.md`

Specs are promoted only after the complete stacked implementation is verified.

## Rollout and Cleanup

The migration forward-converts existing work snapshots to schema version 2, so runtime legacy fallback is unnecessary. No feature flag or provider configuration change is required. The Slack adapter remains the only implemented provider renderer, while the canonical contract is ready for future Discord and GitHub adapters.

Remove this plan in the final cleanup/spec-promotion PR after verification. Do not merge any PR in the stack without explicit requester approval.
