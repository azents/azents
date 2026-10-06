---
title: "Memory Summary Workflow Implementation Plan"
created: 2026-10-06
tags: [memory, implementation, lifecycle, frontend]
---

# Memory Summary Workflow Implementation Plan

- Requirements: [memory-261006/REQ](../requirements/memory-261006-summary-workflow.md)
- ADR: [memory-261006/ADR](../adr/memory-261006-summary-workflow.md)
- Design: [memory-261006/DESIGN](../design/memory-261006-summary-workflow.md)
- Approved mechanisms: `M1..M12`, Design revision `1`.
- Design delta: `None`.
- Root/integrated validation owner: `/root`.
- Single independent reviewer: `/root/memory-feature-reviewer`; read-only; root requests each stable integrated phase review.

## Delivery phases

| Phase | PR boundary | Mechanisms | Dependencies |
| --- | --- | --- | --- |
| 1 | Responsive Memory settings, Saved cursor API, current-summary overview, automatic lists and generated clients | M11/M12 | Existing aggregate read storage remains until phase 3 |
| 2 | Common Session/Conversation storage, canonical owner projection, generic lifecycle and real admin diagnostic reads | M5/M6 | Phase 1 PR opened; preserve ordinary conversation/Run/Event identities |
| 3 | Worker consolidation host, provided summaries, shared context/submit/continuation, pending/result conversion and obsolete state/consumer removal | M1/M2/M3/M4/M7/M8/M9/M10 | Phase 2 PR opened; finish integrated E2E/spec promotion/temporary plan cleanup |

Use `Memory Summary Workflow [n/3]: <phase>` PR titles. Create each phase PR before proceeding to the next, and the full series before CI monitoring. Do not merge or deploy. Phase count may only change for reviewability, never to add behavior.

## Shared interfaces and preservation

- Phase 1 public Saved paging: cursor/limit -> items/next_cursor; lexical filters and exact scope unchanged. UI current-summary route resolves current authenticated User and current result in selected scope, with no generation side effect.
- Phase 1 uses existing aggregate read rules; phase 3 replaces their obsolete manifest/revision consumers. This dependency does not retain them in the final system.
- Common Session owns durable Run/Event and execution owner. Conversation-only fields use one profile relation and one writer; no internal placeholder Conversation.
- Internal execution has no public Conversation identity; admin diagnostics expose retained safe canonical records with current existing system-admin authentication.
- Common purge is one eligibility/job/resource/checkpoint/finalizer pipeline. Retain audit payload until policy expiry; current result/source/Saved/pending/scalar outcome is outside execution payload cascade.
- Submit acceptance and execution-associated work settlement are atomic; no Agent ledger/versioning or all-pending auto-ack.
- Current absolute deadline/turn and retention settings remain. No new role/UI, queue/fairness mode or compatibility fallback.

## Scope and removal

Each phase owns the corresponding Design Removal and Replacement rows. Phase 3 must remove source-dependency and authoring-version behavior from host, repositories, foreground snapshots, consolidated VFS, UI read, model/schema, prompt/test/fixture and current specs. Old historical snapshots remain unchanged. Data-preserving Alembic migration and old/new writer exclusion are prerequisites for activation; live handover is not performed.

## Validation and external prerequisites

Root owns final integrated Ruff/format/typechecker/Pytest and frontend format/lint/typecheck/build, public route/client, migration and browser/Storybook/E2E evidence. Deterministic tests use explicit synchronization. Real small-window/model/representative quality tests retain resolved metadata; absent optional live credentials are explicitly skipped, not silently credited. Do not log private input bodies.

No production DB/cluster operations. Local isolated test DB and browser/devenv may be used under their project workflow. Keep applicable CI topology. Update Living Specs with reachable changes; mark Requirements/Design implemented only after full validation. Remove all temporary feature phase plans in final feature cleanup.

## Context checkpoint

Initial: base `b5e819ac`, worktree `feature/memory-summary-workflow-261006`. Requirements/ADR/Design formalized from explicit implementation authorization. No code changes yet. Storage and lifecycle scouts are read-only evidence lanes; the reviewer is not an implementation owner. Known hazards: public DTO/execution authority shared converter, active-primary constraint after profile extraction, ROOT purge prerequisites, early live-worktree cleanup versus durable audit payload, manifest-bearing foreground consumers. These are required preservation/verification work, not additional product decisions.
