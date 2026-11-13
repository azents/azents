---
title: "Work continuity across execution segments Requirements"
created: 2026-11-13
implemented: 2026-11-13
tags: [backend, engine, continuation]
document_role: primary
document_type: requirements
snapshot_id: continuation-261113
---

# Work continuity across execution segments Requirements

- Snapshot: `continuation-261113`
- Document reference: `continuation-261113/REQ`

## Problem

An admitted obligation can outlive an individual execution segment. Continuing after a durable action currently loses the association needed to report progress or complete some kinds of work, even though the same logical work is still being performed. Repeating an unrelated continuation merely to recover completion authority is incorrect.

## Primary System Outcome

Logical work remains identifiable and completable across execution-segment changes through every supported continuation path, without coupling work identity or completion to one particular segment.

## Supporting Scenarios or Effects

- A scheduled occurrence creates a managed worktree, performs work, removes the worktree, and submits its result without an additional recovery-only execution.
- Several selected Routine occurrences can share execution while retaining independent results.
- Goal and external-channel work continue without changing their existing user-visible lifecycle contracts.

## Goals

- Preserve exact work context through continuation, retry and recovery.
- Separate logical work authority from execution-segment identity.
- Preserve isolation, cancellation, Stop, and idempotent completion.

## Non-Goals

- Merge the lifecycle or terminal meaning of Scheduled Tasks, Routines, Goals, Channel Work or durable actions.
- Add a user-facing workflow product, new scheduling policy, execution mode, or automatic operational repair.
- Remove execution ordering, ownership fences, audit provenance or provider-native response continuation identities.
- Change notification policy or perform production mutation/deployment.

## Requirements

### REQ-1. Work survives execution-segment changes

All supported semantic continuations retain the exact work being continued independently of the identity of the consuming execution segment.

**Acceptance criteria**

- Worktree creation and removal do not break scheduled progress or result submission.
- Goal, Channel Work, Scheduled Task, Routine and durable-action continuations preserve their applicable work context.
- Repeated continuation does not require domain-specific reassignment to each successive execution segment.

### REQ-2. Independent obligations remain independent

A continuation can carry no logical obligation or more than one; continuation does not conflate completion of different obligations.

**Acceptance criteria**

- Completing one Routine occurrence leaves other occurrences unfinished.
- Completing a scheduled occurrence does not complete a Goal or Channel Work.
- Ordinary inputs do not acquire arbitrary active obligations merely because they share a Session.

### REQ-3. Preserve authority and stale-work rejection

Separating work from execution must retain exact ownership, provenance, current-state and cancellation checks.

**Acceptance criteria**

- Foreign, stale, cancelled and already-replaced obligations cannot be completed by guessed identifiers.
- Superseded execution owners cannot mutate current work or publish its output.
- Stop, archive and deletion retain their existing scope and exceptions.
- Duplicate continuations and duplicate terminal submissions cannot create duplicate results or effects.

### REQ-4. Preserve continuity through lifecycle boundaries

Retry, ownership takeover, action completion, idle continuation, inter-agent input and compaction must not silently lose applicable work context or grant unrelated work authority.

**Acceptance criteria**

- Explicit retry and ownership recovery preserve valid admitted work.
- Canonical work context is not reconstructed from model text or compacted summaries.
- Inter-agent messages do not transfer a child's separate obligations to a parent or vice versa.
- Existing admitted durable work is preserved during storage changes.

### REQ-5. Keep domain behavior unchanged

Only execution coupling and work-context propagation change; task selection, schedules, result semantics and notification behavior remain unchanged.

**Acceptance criteria**

- Existing domain and execution tests continue to validate their meaningful contracts.
- Minimal end-to-end work continuity is covered; combinations and failure ordering are tested at lower layers.

### REQ-6. Select the exact logical work item

Tools that advance or complete an existing logical obligation must unambiguously select that obligation rather than silently operating on whichever one is currently inferred from an execution segment or replacement state.

**Acceptance criteria**

- The model receives the exact server-issued identifiers needed by the applicable tools, with enough title and occurrence context to distinguish work items.
- Scheduled results explicitly identify their occurrence; several admitted Scheduled occurrences can be handled without overwriting or implicitly choosing another occurrence.
- Analogous Routine, Goal and Channel Work operations use the same exact-work principle while retaining their existing independent lifecycle and single/multiple-work policies.
- A stale identifier cannot finish a later replacement item. Knowing an identifier alone does not grant work authority.
- Continuation exposes the identity of the work actually continued, including continuations caused by durable actions.

### REQ-7. Preserve identity through the established compaction boundary

Work identity needed for further tool calls survives successful compaction through the established server-owned context and enrichment contracts.

**Acceptance criteria**

- Scheduled occurrence identity is included in the appropriate server-authored work snapshot, rather than depending on a summarizing model to reproduce hidden identifiers.
- Auto, manual and input-limit-recovery compaction preserve applicable work context.
- Hook failure remains fail-open, continuity remains last, and stale/failed/cancelled attempts do not establish a new summary/head or new work authority.
- Summary visibility does not admit unrelated work or revive completed/cancelled items.
- Run, lease, provider-message and unrelated internal ownership identifiers remain undisclosed.

## Fixed Constraints

- Existing Session execution-generation fencing remains the mutation authority.
- No operational database edits, merge or deployment are authorized by this work.
- New stored data must preserve existing admitted work through a migration, without an indefinite compatibility fallback.

## Open Assumptions

- None that change the requested outcome. Material choices outside the approved separation/context-propagation direction require requester input.

## Confirmation

The requester explicitly asked to decouple Scheduled Task identity from AgentRun, expanded the request to all other continuation kinds, and on 2026-11-13 instructed implementation after the scope, preserved authority boundaries and independent domain semantics had been presented. The requester subsequently approved explicit model-visible occurrence identifiers, exact identifier selection by completion tools, inclusion in continuation and spec-correct compaction handling, and the same treatment for analogous tools. REQ-6 and REQ-7 record that extension. This snapshot records confirmed intent; it does not assert approval of undisclosed material mechanisms.
