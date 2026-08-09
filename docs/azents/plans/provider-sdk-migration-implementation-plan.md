---
title: "Provider SDK Migration Implementation Plan"
created: 2026-08-09
updated: 2026-08-09
tags: [external-channel, slack, discord, sdk, implementation]
---

# Provider SDK Migration Implementation Plan

## Authority Baseline

- Requirements: [external-260809/REQ](../requirements/external-260809-provider-integration-reliability.md)
- ADR: [external-260809/ADR](../adr/external-260809-provider-integration-reliability.md)
- Design: [external-260809/DESIGN](../design/external-260809-provider-integration-reliability.md), revision `1`
- Approved mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8`
- Decision owner: requester
- Implementation owner: root agent
- Independent reviewer: `provider-sdk-reviewer`
- Design delta: `None`

## Delivery Shape

Use three stacked PRs so control/history migration, delivery/file migration, and final deterministic verification/spec promotion remain independently reviewable. Create the full stack before monitoring CI.

| Phase | Branch → base | Deliverable | Approved mechanisms |
| --- | --- | --- | --- |
| 1/3 | `azents/provider-sdk-migration` → `main` | Discord public SDK lifecycle, Application/identity/command/history migration, G1 command-create gap | M1, M2, M4, M5, M7, M8 |
| 2/3 | `azents/provider-sdk-migration-delivery` → phase 1 | Discord delivery/thread/file migration, G2/G3, Slack G4/G5 transport split | M1, M2, M3, M4, M5, M7, M8 |
| 3/3 | `azents/provider-sdk-migration-validation` → phase 2 | deterministic SDK-facing fixtures, private-SDK removal, static checks, full validation, Specs, implemented dates, plan cleanup | M5, M6, M7, M8 |

PR titles use `provider SDK migration [n/3]: <phase>`.

## Interfaces and Integration Boundaries

- `DiscordSDKClientFactory` and request-scoped public `discord.Client` context are introduced in phase 1 and remain stable for phases 2 and 3.
- Provider adapters return existing Azents domain DTOs and provider-neutral outcomes; no persistence or public API schema changes.
- Direct transports expose only approved gap operations G1-G5 and no generic request method.
- Phase 2 consumes phase 1 SDK lifecycle without changing its material authority.
- Phase 3 may refine test-only collaborator composition and static scans but cannot change provider runtime behavior.

## Workstreams and Dependencies

1. SDK lifecycle and exception mapping.
2. Discord control-plane and history conversion.
3. Discord delivery and file conversion.
4. Slack byte-transport separation.
5. Dependency wiring and deterministic fixtures.
6. Direct-call/private-SDK absence enforcement.
7. E2E, quality, Living Spec promotion, and plan cleanup.

## Data, API, Runtime, and Rollout

- Database migrations: none.
- Public API/OpenAPI changes: none expected; absence verified in phase 3.
- Runtime configuration: no new production variable or mode.
- Production dependencies: no new SDK; retain `discord-py` and `slack-sdk`.
- Rollout: ordinary server/gateway code rollout with existing database lease fencing.
- Rollback: code rollback only; no dual provider path or data rollback.

## Test and E2E Prerequisites

- Credential-free Slack and Discord provider fakes remain required.
- Existing External Channel deterministic E2E journeys are the primary evidence.
- Provider fixtures retain sanitized operation evidence only.
- Optional live credentials are not required and cannot replace deterministic evidence.

## Removal Obligations

- Delete SDK-supported Discord raw HTTP routes, payload parsers, retry/error duplication, and dependency providers.
- Remove general Slack `httpx` injection from SDK-supported paths.
- Delete private `discord.http` and `discord.gateway` imports and deterministic endpoint mutation.
- Replace route-level fixtures for SDK-supported behavior with SDK-facing fakes.
- Retain direct HTTP only in G1-G5 operation-specific modules.

Absence evidence is provided by focused grep/AST tests, no provider API route literals outside approved gaps, no private SDK imports, no generic provider HTTP client, and passing deterministic E2E.

## Context Checkpoints

After each phase record changed interfaces, implemented mechanisms, removal evidence, focused validation, review findings, remaining phases, risks, and blockers in the phase plan and PR body. The same `provider-sdk-reviewer` reviews every phase from the Requirements, ADR, Design, current Specs, phase contract, and diff.

## Spec Impact and Cleanup

Phase 3 runs `/spec-review`, updates External Channel domain/delivery/provider-ingress Specs, adds the common `implemented: 2026-08-09` date only after complete validation, and deletes this plan plus all phase plans before the final PR is complete.

## External Actions and Blockers

No live provider action, credential, Kubernetes change, migration, or operator configuration is required. CI waits are not blockers. Any new product contract or material mechanism returns to `feature-design`; current Design delta is `None`.
