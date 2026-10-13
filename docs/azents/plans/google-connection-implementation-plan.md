---
title: "Google Connection Implementation Plan"
created: 2026-10-13
tags: [google, toolkit, implementation, testing]
---

# Google Connection Implementation Plan

- Inputs: [Requirements](../requirements/google-261013-connection.md),
  [accepted ADR](../adr/google-261013-connection.md), and
  [approved Design revision 4](../design/google-261013-connection.md).
- Approved mechanisms: `M1` through `M16`; authorities are the Design authority
  table and ADR-D1 through ADR-D4 including direct activation and explicit
  Connect/Reconnect fresh-renewal clarifications.
- Design delta: None.
- Sole implementation/integration/validation owner: `/root`, as requested.
- Exact independent read-only reviewer for every stable integrated phase:
  `/root/google-feature-reviewer`. Design approval owner remains read-only.

## Delivery Shape

| Phase | Branch/base | Deliverable | PR boundary |
| --- | --- | --- | --- |
| 1 | `design/google-261013-connection` → `main` | Operator Section, typed scopes/screening, OAuth/grant lifecycle, management API, service routing/renewal, focused deterministic tests and generated clients | Existing #2252 becomes Google connection [1/3]: backend |
| 2 | `feature/google-261013-ui` → phase 1 branch | Progressive Google setup, same-context callback, actual reduced-capability review/reconnect, Admin operator preparation, localized accessible UI | Google connection [2/3]: UI |
| 3 | `feature/google-261013-verification` → phase 2 branch | Required provider/Web E2E, fixture interleavings, current Specs, same-SHA integrated QA and temporary-plan cleanup | Google connection [3/3]: verification |

Open each phase PR before starting its successor. Do not merge without explicit
merge authority. No separate design/cleanup PR is added just to match the process.

## Contracts and Integration

- `google_oauth` is a direct typed operator System Settings Section. Current
  registration and generation, not per-Toolkit secret copies, own app credentials.
- A Google Toolkit stores explicit tasks, existing MCP timeout, and fresh reviewed
  security acknowledgement. One subject/client-bound grant has proved scopes.
- Exact unpublished attempts cover creation/reconnect. Claim, stage, publication,
  cancellation/outcome and disconnect are repository-owned atomic operations.
- Supported Authlib/Google identity APIs perform external I/O between completed
  transactions. Current canonical Session owner generation governs tool effects.
- Per-service exact tool policy intersects current selection and grant evidence.
  Runtime projection and call admission use the same current policy.
- Bounded screening precedes remote schema exposure, outbound calls, inbound
  extraction and artifacts. Unsupported binary results fail closed.
- Generated clients come from OpenAPI, never hand edits. Phase 2 consumes stable
  phase 1 public contracts; phase 3 verifies the integrated product path.

## Verification and Prerequisites

Root runs focused unit/repository/service/route checks while building, then
integrated Ruff, type checking, Python tests, generated-client checks, frontend
format/lint/types/build and required/Web E2E as applicable. Deterministic testenv
OAuth/MCP fixtures provide partial/unknown grants, identity failures, refresh and
publication races. Explicit barriers establish interleavings.

Live Google credentials and Preview eligibility are not available or authorized.
No consent, live data/write, paid scanner activation or production change occurs.
Live mapping/interoperability/renewal/screening efficacy are reported conditional,
not conflated with fixture success. Observe/reuse only this Session's development
environment; no other Session data reset.

## Removal and Current Specs

Preserve generic MCP, GitHub, GCP, Analytics, Notion/Sentry and existing data.
Remove any implementation prototypes/bypasses in the owning phase; one Google
path remains. Candidate cleanup deletes local ciphertext without Google revocation.
No retired-secret fallback or product version history is added.

Update current Toolkit, OAuth, System Settings and relevant execution/UI Specs
where implemented behavior changes. Mark Requirements/Design implemented only
after integrated validation; remove this plan and all phase plans in phase 3.
Verify absence through call-site/config/schema search and primary E2E.

## Context Checkpoints

At each phase record exact SHA/PR, implemented interfaces, authority/scope check,
removals, reviewer findings/resolution, root validation evidence, remaining paths
and live limits. A new material mechanism returns to Design, not plan authority.

Phase 1 checkpoint: `cdefeda1ad0fd255d1171a5228126b3ca33025cb`, PR #2252,
approved revision 4 M1–M16. The same independent reviewer approved all integrated
review corrections and the enum-order migration correction. Root validation:
12,299 backend tests passed, three existing Redis-only skips; 26 migration tests,
16 client template tests and 18 documentation tests passed. Latest-SHA CI run
38448628646 succeeded, including required four-shard and Web E2E. No merge or
live Google access occurred. Main's retention schema remains preserved.

Phase 2 starts on `feature/google-261013-ui` with its tracked UI execution plan.
Root implements the management surfaces; product-specific E2E, integrated QA,
Spec promotion and plan cleanup remain in phase 3.
