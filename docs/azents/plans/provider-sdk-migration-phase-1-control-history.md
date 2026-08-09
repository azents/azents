---
title: "Provider SDK Migration Phase 1 Control and History Plan"
created: 2026-08-09
updated: 2026-08-09
tags: [external-channel, discord, sdk, implementation]
---

# Provider SDK Migration Phase 1 Control and History

## Phase Execution Plan

- Phase: `1/3 — Discord SDK control and history`
- Branch/base: `azents/provider-sdk-migration` → `main`
- PR boundary: public `discord.py` REST lifecycle plus Application, identity, preservation-safe command reconciliation, exact-message/history conversion, and G1 isolation
- Inputs: confirmed `external-260809/REQ`, accepted `external-260809/ADR`, approved Design revision `1`
- Deliverables: SDK-owned Discord control/history operations, operation-specific command-create REST gap, focused tests, no change to delivery/file runtime
- Non-goals: message/thread delivery migration, file byte transport, Slack transport split, final testenv Gateway replacement, Living Spec promotion
- Interfaces: request-scoped `DiscordSDKClientFactory`; bounded SDK projection DTOs; `DiscordGuildCommandCreateTransport`; existing `DiscordAPIClient` and `DiscordConversationHistoryClient` service-facing methods remain behavior-compatible
- Approved Design mechanisms: `M1, M2, M4, M5, M7, M8`
- Authority references: `external-260809/REQ-1, REQ-2, REQ-3, REQ-5, REQ-6, REQ-7`; `external-260809/ADR-D1, D2, D4`; External Channel and Provider Ingress Specs
- Design delta: `None`
- Removal obligations: general Discord control/history HTTP clients and SDK-supported route parsing; retain only G1 command create
- Absence verification: no direct Application, identity, command list/edit/delete, exact-message, or history route request remains; no Hikari or second SDK dependency/import

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| SDK lifecycle | root | `discord_sdk.py` or equivalent new adapter module; dependency wiring used by activation/history | None | public `discord.Client.login/close` context, public exception mapping, bounded DTOs | focused lifecycle and mapping tests |
| Application and commands | root | `discord_api.py`, `discord_activation.py`, related tests | SDK lifecycle | SDK Application/identity/list/edit/delete plus G1 create transport | command preservation and activation tests |
| History | root | `discord_history.py`, `ingestion_history.py`, `discord_events.py` projection helpers, related tests | SDK lifecycle | public exact-message/history iteration and bounded normalization | history bounds, trigger, pagination, malformed identity tests |
| Removal and scan | root | obsolete HTTP dependency providers/tests in owned phase paths; static focused assertions | preceding workstreams | no SDK-supported direct control/history routes | grep/AST absence checks and `git diff --check` |

- Integration order: SDK lifecycle → Application/command adapter → history adapter → dependency wiring → obsolete path removal → focused validation
- Independent review: `provider-sdk-reviewer`; read-only review against Requirements, ADR, Design M1/M2/M4/M5/M7/M8, phase plan, current Specs, and complete phase diff; report only correctness, security/data-loss, contract, convention, interface, and material removal findings
- Final validation: Ruff format/lint on changed files; Pyright/ty on affected External Channel paths; focused `discord_api`, activation, history, ingestion-history, and SDK lifecycle tests; `git diff --check`; direct-route/private-SDK scan
- Scope-drift check: every phase-1 replacement and removal is present; no delivery/file/Slack behavior change; no new SDK, state, configuration, fallback, public API, or material mechanism
- Context checkpoint: record SDK lifecycle interface, operations migrated, G1 exact boundary, tests, removals, review result, remaining phase-2 dependency, and any non-blocking risk before commit and PR creation
