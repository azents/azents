---
title: "External Channel Request Input Phase 2 Plan"
created: 2026-08-31
tags: [external-channel, backend, engine, e2e, documentation]
---

# External Channel Request Input Phase 2 Plan

## Phase Execution Plan

- Phase: `2/2 — same-binding resume and awaiting projections`
- Branch/base: `feature/channel-action-request-input-resume` → `feature/channel-action-request-input`
- PR boundary: participant-input resume, ready-only idle continuation, awaiting compaction, Slack/Discord presence behavior, E2E, Living Specs, implementation completion, and plan cleanup
- Inputs: phase-1 mode, schema version 4, request transition, delivery-confirmed settlement, and migration
- Deliverables: awaiting Work is resumed only by newly created same-binding human input or `continue`; idle continuation and active presence exclude awaiting Work while context remains visible
- Non-goals: provider-native reply correlation, interaction UI, new public lifecycle enum, feature flags, or live-provider-only verification
- Interfaces: `ExternalChannelWorkRepository.resume_from_human_input`, `ChannelWorkSnapshot.awaiting_input`, ingress `created` boundaries, idle hook binding selection, compaction rendering, Slack presence and Discord typing projections
- Approved Design mechanisms: `M1, M2, M3, M5, M6, M10, M11`
- Authority references: `channel-260831/REQ-1`, `channel-260831/REQ-2`, `channel-260831/REQ-3`, `channel-260831/ADR-D1`, `channel-260831/ADR-D2`, `channel-260831/ADR-D5`, `channel-260831/ADR-D6`, current Agent Execution Loop and External Channel Delivery Specs
- Design delta: `None`
- Removal obligations: remove unconditional idle eligibility and active processing presence for awaiting Work; preserve Tracker, tasks, and normal ingress
- Absence verification: duplicate/failed/provisioning ingress tests do not resume; no interaction routes or lock paths; ready-only continuation and typing/presence tests

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Resume authority | `/root` | `repos/external_channel/work.py`, `services/external_channel/{ingress_queue.py,mailbox_ingestion_store.py}` and tests | Phase-1 state | Created same-binding human mailbox input clears awaiting and advances revision | Admission, duplicate, failed, and race tests |
| Continuity | `/root` | `engine/tools/external_channel.py` and tests | Snapshot awaiting flag | Ready-only idle continuation and awaiting compaction indicator | Hook and compaction tests |
| Presence | `/root` | `repos/external_channel/repository.py`, Slack presence and Discord Gateway tests | Version-4 state readers | Slack idle projection and no Discord typing while awaiting | Repository/manager projection tests |
| Product verification | `/root` | `testenv/azents/**`, affected deterministic E2E | Integrated behavior | Slack and Discord lifecycle evidence | Required E2E |
| Spec promotion and cleanup | `/root` | affected `docs/azents/spec/**`, Requirements/Design frontmatter, `docs/azents/plans/**` | Passing validation | Current behavior specs, implemented date, deleted temporary plans | Spec review and docs hooks |

- Integration order: repository resume mutation → both canonical ingress paths → idle/compaction → presence/typing → focused tests → E2E → specs/implementation markers → plan cleanup
- Independent review: `hardtack`; verify same-binding and `created` authority, no resume from duplicates/provisioning/other bindings, ready-only continuation, Tracker preservation, and no new lock or provider UX
- Final validation: backend Ruff/format/type check and affected pytest; E2E Ruff/format/type check and deterministic External Channel E2E; docs/spec validation
- Scope-drift check: every phase diff maps to M1/M2/M3/M5/M6/M10/M11; no new correlation, API enum, prompt surface, persistence store, lock, or rollout mode
- Context checkpoint: record complete lifecycle evidence, presence and continuation behavior, spec promotion, removed plans, remaining risks, and final stack relationship
