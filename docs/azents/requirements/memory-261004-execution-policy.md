---
title: "Historical Memory Execution Policy Requirements"
created: 2026-10-04
implemented: 2026-10-04
tags: [memory, backend, observability, system-settings]
document_role: primary
document_type: requirements
snapshot_id: memory-261004
---

# Historical Memory Execution Policy Requirements

- Snapshot: `memory-261004`
- Document reference: `memory-261004/REQ`

## Problem

Consolidation has additional execution restrictions absent from the main Agent. Healthy model/tool work can fail before useful publication because of fixed cumulative token, dispatch, tool, or working-file budgets. Internal failures are reduced to opaque persisted codes without a reliable terminal ERROR traceback, making diagnosis difficult.

## Primary System Outcome

Historical Memory consolidation follows the main Agent's model and generic-tool execution contracts. Its only additional execution cutoffs are system-configurable maximum turns and elapsed time. Internal faults remain observable to operators rather than becoming user-actionable database errors.

## Supporting Effects

- Operators can configure both execution cutoffs through existing System Settings.
- Scalar usage and retry state remain truthful without imposing a separate spend budget.
- Existing scope isolation, durable source authority, publication validation, and foreground behavior remain intact.

## Goals

- Remove memory-only execution restrictions instead of making them optional.
- Expose actionable failures separately from internal operational faults.

## Non-Goals

- Change Saved Memory, Team/User ownership, source authorization, or the 10k-per-unit/20k-foreground publication contract.
- Deploy, merge, modify production settings/data, or force live jobs.
- Add provider fallbacks, new sources of truth, or a separate execution loop.

## Requirements

### REQ-1. Use the main Agent execution contract

Input and output behavior follows the selected model's resolved settings and shared tool contracts. Consolidation must not add cumulative input/output budgets, a fixed per-call output ceiling, dispatch/tool-count limits, a separate input-window percentage cutoff, or working-file capacity restrictions absent from the main Agent.

**Acceptance criteria**

- A valid request is not refused solely because earlier requests consumed a fixed memory-only token budget.
- Generic tool work and drafts are not refused by memory-only invocation/file/byte caps.
- Shared provider, storage/tool validation and source authorization remain enforced.

### REQ-2. Configure permitted cutoffs through System Settings

Maximum turns and execution time are system settings, not per-Agent additions or hidden fixed constants.

**Acceptance criteria**

- System administrators can read and update both values using existing System Settings management.
- New attempts use the effective settings; a running attempt has one coherent immutable policy/deadline.
- Maximum turns has the same meaning as the shared main Agent iteration core, not physical requests or tools.
- Time changes affect the attempt supervisor, durable claim and submitted Job Runtime deadline consistently.

### REQ-3. Distinguish actionable errors from internal faults

Persisted error information is restricted to errors users can act on or need to inspect. Database contention, stale execution authority, internal execution failures, server timeouts and automatic cutoff failures must not be persisted as user error codes.

**Acceptance criteria**

- Internal failures emit an ERROR log with origin traceback and safe job/attempt identity.
- Internal failure settlement does not populate `failure_code`; execution/retry state still settles accurately.
- Actionable authentication, permission, quota/billing or selected-model availability errors can retain safe codes.
- No raw provider body, credentials, memory body or hidden reasoning is added to logs.
- The registered Job Runtime does not silently convert uncaught exceptions into unobserved outcomes.

## Fixed Constraints

- Preserve Team/User isolation, exact manifests, generation fences and atomic publication.
- Reuse the shared iteration core, model settings resolution, System Settings and logger integration.
- Current implementation starts from freshly pulled `origin/main` at `148835d55`.
- Implemented earlier Requirements/ADR/Design remain immutable.

## Open Assumptions

- Maximum-turn absence retains the main Agent's unlimited-turn representation; elapsed time remains configurable with the current ten-minute value as its initial system default.
- Page sizes used to bound database retrieval are batching mechanics, not attempt termination budgets.

## Confirmation

The requester directly required removal of main-Agent-absent restrictions, system-configurable maximum turns and elapsed time, and correction of internal-fault persistence/logging on 2026-10-04 before implementation. These explicit instructions confirm REQ-1–3. No new product behavior or live operation is inferred.
