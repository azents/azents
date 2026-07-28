---
title: "Discord Slack Parity Implementation Plan"
created: 2026-07-28
tags: [discord, slack, external-channel, backend, frontend, testenv, documentation]
---

# Discord Slack Parity Implementation Plan

## Source of truth

- Requirements: `docs/azents/requirements/discord-260728-slack-parity.md`
- ADR: `docs/azents/adr/discord-260728-slack-parity.md`
- Design: `docs/azents/design/discord-260728-slack-parity.md`
- Relevant current specs:
  - `docs/azents/spec/domain/external-channel.md`
  - `docs/azents/spec/flow/external-channel-provider-ingress.md`
  - `docs/azents/spec/flow/external-channel-authorization.md`
  - `docs/azents/spec/flow/external-channel-delivery.md`
  - `docs/azents/spec/flow/external-channel-lifecycle.md`
  - `docs/azents/spec/flow/test-strategy-e2e-primary.md`

## Delivery shape

The requester explicitly requires one PR implemented directly by the primary agent.
This plan therefore uses one reviewable end-to-end PR rather than the normally
recommended stacked delivery. It includes the approved snapshot, this temporary plan,
one phase execution plan, implementation, generated artifacts, tests, and spec
promotion. It does not merge or deploy the PR.

## Ownership

| Role | Owner | Scope |
| --- | --- | --- |
| Implementation | `/root` primary agent | All backend, generated API, web UI, E2E, and documentation changes |
| Validation and review | `/root` primary agent | Focused tests, quality checks, E2E, diff/spec review, PR CI remediation |

No implementation work is delegated, per requester instruction.

## One-PR execution phases

| Phase | Boundary | Depends on | Completion evidence |
| --- | --- | --- | --- |
| 1 | Interaction, selected-source, and selector parity | Current admission/selector contracts | Focused parser, HTTP, and selector tests |
| 2 | Thread target, hydration, activation, work, and lifecycle parity | Phase 1 | Focused event/delivery/work tests and deterministic participant E2E |
| 3 | Discord Multi public API, generated clients, tRPC, and Workspace UI | Existing provider-neutral management service | API tests, regenerated clients, TypeScript checks, browser E2E |
| 4 | Final validation and spec promotion | Phases 1–3 | Required checks, deterministic E2E, `/spec-review`, docs index, CI green |

Phases are sequential where they share the canonical resource and delivery contract.
Focused API/UI work may begin after the provider-neutral management boundary is verified,
but is not committed separately.

## Interface and persistence constraints

- PostgreSQL remains canonical for claims, resources, bindings, work, delivery, leases,
  configuration generation, and app-claim generation.
- Do not introduce Discord-specific authorization, Session, binding, work, or lifecycle
  persistence domains.
- Interaction signatures, tokens, raw requests, provider payloads, attachment URLs or
  bytes, selector values, and exception text remain transient or redacted.
- Root and existing-thread conversations resolve one deterministic Discord delivery
  thread before controls, Session links, progress, replies, or files are delivered.
- Existing Discord `ExternalChannelWorkProjectionPart` page state remains authoritative
  for Discord progress projection; no best-effort status-message path is added.
- Public API changes require OpenAPI dump and generated Python/TypeScript clients. No
  generated client is hand-edited.

## E2E primary verification matrix

| User-visible behavior | Primary evidence | Supporting evidence |
| --- | --- | --- |
| Message Command source and selector choice | Deterministic Discord fake E2E | Parser/HTTP/selector unit tests |
| Approval release and Session wake in one thread | Deterministic participant E2E | Event processor and delivery tests |
| History hydration and existing-thread reuse | Deterministic participant E2E | Normalization/hydration tests |
| Progress page update, deletion recovery, final cleanup, and files | Deterministic participant E2E | Work/delivery tests |
| Discord Multi management | Deterministic public API E2E | Route/service/client tests |
| Workspace management UI | Web Surface browser E2E | TypeScript unit/type/lint/build checks |

The existing credential-free deterministic Discord provider fake is the required fixture
substrate. No new live credential or prerequisite is required. Any unavailable local
Docker/Testcontainers or browser prerequisite is reported as blocked evidence and is not
represented as a passing live-equivalent test.

## Validation and cleanup

1. Run narrow Python and TypeScript checks while editing, then relevant complete checks.
2. Dump OpenAPI and regenerate affected clients through repository scripts.
3. Run deterministic and web-surface E2E paths selected by affected code.
4. Run `/spec-review`; update current specs and their verification metadata only for
   behavior implemented in this PR.
5. Mark Requirements and Design `implemented` only after local validation and PR CI
   are green.
6. Remove this plan and the phase plan only in a later cleanup PR; this single delivery
   PR retains them while the feature is active.
