---
title: "Transaction Ownership Phase 16: Residual Services and Worker Entrypoints"
created: 2026-10-01
tags: [backend, worker, external-channel, runtime, architecture, database]
---

# Phase Execution Plan

- Phase: `16, residual service and Worker completed operations`
- Branch/base: `refactor/transaction-ownership-261001-4-residual-services` → `refactor/transaction-ownership-261001-3-agent-services`
- PR boundary: replace the bounded remaining application-owned transaction contexts in Chat Workspace access, Discord settings/gateway activation management, idle continuation, and evidence-backed residual service/Worker entrypoints with typed completed repository operations.
- Inputs: Phase 15 Agent service operations and the approved `transaction-260908` Requirements, ADR, and Design revision 1.
- Deliverables: completed Workspace access reads, Discord interaction and gateway lifecycle operations, idle eligibility/finalization operations, and an updated residual inventory with explicit exclusions or deferrals to final validation.
- Non-goals: Discord protocol/UI changes, Runtime file semantics, idle-hook semantics, broker/event ordering changes, new leases/locks/retries/fallbacks, schema/API/configuration changes, or infrastructure actions.
- Interfaces: existing Workspace membership errors, Discord origin/lease/generation fences, idle owner-generation and archived Scheduled continuation predicates, mailbox atomicity, publication ordering, and cancellation behavior remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`, `transaction-260908/ADR-D1` through `ADR-D3`, and `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove direct transaction ownership from the assigned service/Worker entrypoints and replace session-taking service helpers with repository-owned database-only composition.
- Absence verification: direct-session searches across assigned paths, repository-to-service import search, external-I/O call-path review, and final residual inventory classification.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Chat Workspace access | `/root` | `services/chat/workspace.py`, completed repository and tests | Agent and WorkspaceUser repositories | Completed Agent/member authority snapshot before Runtime work | Workspace service and repository tests; no direct session context |
| Discord settings and gateway lifecycle | `/root` | `services/external_channel/discord_settings.py`, `discord_gateway_manager.py`, `discord_activation.py`, bounded repositories/tests | Existing External Channel repositories and lease contracts | Completed origin validation and gateway lifecycle DB operations around Discord network work | Discord settings/gateway/activation focused suites; ordering checks |
| Idle continuation | `/root` | `worker/session/idle_continuation.py`, completed repository and tests | Session/Run/Mailbox/Scheduled Cycle repositories | Pre-hook eligibility read plus post-hook atomic revalidation/enqueue/consume operation | Owner-generation, archived cycle, mailbox atomicity, publication-order tests |
| Residual inventory | `/root` | assigned evidence note/plan and bounded directly dependent entrypoints | All workstreams | Explicit corrected/excluded/remaining classifications | lexical plus call-path search; no unsupported completeness claim |

- Integration order: implement small completed read operations, extract idle finalization, migrate Discord lifecycle operations in existing lock order, update tests/Specs, then run the residual search.
- Independent review: `/root/issue-hardening-review` performs one read-only review after all implementation workstreams are complete and the integrated diff is stable.
- Final validation: root runs changed-path Ruff and format, full backend `ty`, focused Chat/Discord/Worker pytest, pre-commit, transaction/import searches, and creates the stacked PR.
- Scope-drift check: confirm preserved authority, atomicity, errors, publication order, cancellation, and lease/owner fences; add no lock, queue, retry, fallback, API, schema, protocol, or configuration mechanism absent from Design Authority.
- Context checkpoint: PRs #2005, #2006, and #2007 form the preceding stack. Phase 16 owns the final implementation slice before the separate inventory, integrated validation, Spec promotion, implementation marking, and temporary-plan cleanup phase.
