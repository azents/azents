---
title: "Memory Summary Workflow Requirements"
document_role: primary
document_type: requirements
snapshot_id: memory-261006
created: 2026-10-06
implemented: 2026-10-07
tags: [memory, agent, lifecycle, frontend]
---

# Memory Summary Workflow Requirements

- Snapshot: `memory-261006`
- Reference: `memory-261006/REQ`

## Problem

Historical Memory consolidation combines authoring with file versions, inherited source dependencies, an Agent processing ledger, and a separate execution lifecycle. Correctable output failures can end useful work, while committed output can be confused with failed cleanup. The settings screen emphasizes session entries rather than the integrated memory and requires manual pagination.

## Primary Context

### Primary System Outcome

An isolated internal Agent produces a fresh integrated Markdown memory from eligible prepared session summaries using the common durable execution foundation, completes through explicit accepted submission, and remains inspectable during archive retention. Users inspect integrated memory first and load memory lists incrementally.

## Supporting Scenarios or Effects

- Ordinary conversations retain their current behavior while sharing execution storage and lifecycle.
- Internal executions are private, but authorized operational debugging and audit can inspect retained canonical records.
- Saved Memory remains independently managed.

## Goals

- Simple summary reading, integrated authoring, and explicit submission.
- Shared execution/context/lifecycle without fabricated public conversations.
- Truthful completion, correction, pending-work and cleanup outcomes.
- Responsive settings and automatic incremental lists.

## Non-Goals

- Original-session tools or previous integrated memory as consolidation inputs.
- Product/runtime document versioning, restore/history APIs, file dependency graphs or Agent processing ledgers.
- A second judge model, scoring gate, Memory-specific retry/compaction/purge service.
- New concurrency lanes, fairness settings, timeout increases or admission-time deadline resets.
- A new administration UI, role policy, production rollout or PR merge.

## Requirements

### REQ-1. Eligible prepared summary files

Provide only prepared Markdown summaries of currently authorized, non-archived sessions in the exact Team/personal scope.

**Acceptance criteria**
- Scope/access/archive eligibility is evaluated when files are selected and provided.
- Ineligible contents and internal execution transcripts are not available through discovery or exact file reads.
- Missing/unprepared summaries do not trigger raw transcript fallback.

### REQ-2. Fresh integrated authorship

Create a new integrated result from supplied per-session summaries.

**Acceptance criteria**
- Previous integrated memory is absent from files, prompts and automatic Memory injection.
- Original session/event/tool-result reading is not available to the internal Agent.
- Ordinary user-facing source lookup remains unchanged.

### REQ-3. Authoring autonomy and accurate final size

**Acceptance criteria**
- Exact headings, preambles and source-route punctuation are not independent success requirements.
- Safe server presentation preserves meaning without silently truncating authored content.
- The independently framed final result retains the existing 10,000 UTF-8-byte allowance; feedback measures that result, not total temporary files.
- No useful content does not require invented filler.

### REQ-4. Explicit accepted submission

**Acceptance criteria**
- Final prose and absence of tools do not implicitly publish or complete.
- Submission validates at invocation and is accepted only after durable result/progress persistence.
- Correctable validation failures return actionable tool feedback.

### REQ-5. Same-execution correction and continuation

**Acceptance criteria**
- Unsubmitted normal model endings continue the same execution, dialogue and workspace.
- Correctable submission failures preserve work for correction/resubmission.
- Accepted submission ends without another unnecessary model call.
- Cancellation, ownership loss and admitted deadline/turn exhaustion remain effective; no reset or hidden continuation budget.

### REQ-6. Common Agent execution controls

**Acceptance criteria**
- Model/settings/capability interpretation and provider/tool execution follow common Agent contracts.
- Existing Lightweight selection and approved quota candidate transitions remain; no arbitrary provider/Main fallback.
- No new Memory-only cumulative token/tool/dispatch/file capacity limits.

### REQ-7. Common context lifecycle

**Acceptance criteria**
- The selected provider request fits its actual input window through common context management/compaction.
- Same-execution compaction preserves provided files, authored output and work state.
- Compaction is neither clean-start initialization nor lifetime reset.
- Validation includes a genuinely small resolved request window with growing tool history.

### REQ-8. Durable private execution

**Acceptance criteria**
- Ordinary conversation and consolidation use the common Worker/execution storage foundation.
- RAM is not the sole authoritative internal transcript/work store.
- Internal executions do not appear in ordinary conversation list/exact-ID/event/search/source APIs.
- Routing notifications do not authorize execution or acceptance.
- Internal execution is not a fabricated public ROOT conversation.

### REQ-9. Clean start, audit retention and generic deletion

**Acceptance criteria**
- Fresh hosts receive clean workspaces and current eligible summaries, not predecessor unfinished drafts/dialogue/receipts.
- Same-host corrections/compaction/rollback-confirmed DB retry preserve the workspace.
- Safely settled internal executions are archived using applicable existing retention settings, without forced retention zero.
- Retention preserves queryable canonical inputs, transcript, tool calls/results and terminal state for authorized debug/audit, not only empty metadata.
- Retention eligibility, purge jobs, resource cleanup, checkpoints/retry and finalization use one generalized lifecycle pipeline rather than separate per-kind implementations.
- Startup archives terminal/abandoned predecessors only for the exact unit, never legitimate active owners/unrelated conversations.
- Purging temporary execution payload preserves current accepted memory, sources, pending work and required scalar outcomes.
- Retained audit payload is not replayed into a fresh host and does not introduce file version history/restore.

### REQ-10. Operation-local database contention

**Acceptance criteria**
- Retry only rollback-confirmed database operations with fresh transactions/current authority.
- Preserve obtained model/tool output; do not replay the full external handler.
- Uncertain commits resolve the original durable outcome.
- Descriptive reads do not acquire unrelated writer/latestness exclusion.

### REQ-11. Committed result versus follow-up health

**Acceptance criteria**
- Accepted durable results remain accepted after SDK close, archive or follow-up dispatch errors.
- Secondary faults remain observable and use existing lifecycle/rediscovery.
- Lost acknowledgements do not cause duplicate publication or infer success from a different current document.

### REQ-12. Remove obsolete authoring complexity

**Acceptance criteria**
- Remove authoring file/document revisions/epochs, dependencies and their group conflict/re-read requirements.
- Remove Agent-authored coverage/action/reason bookkeeping.
- Remove prior-aggregate source inheritance and repeated full-source checks.
- Remove exclusively supporting tool contracts, state, schema fields, validation, tests and current documentation; no renamed/optional/legacy equivalent.
- Preserve scope isolation, execution owner/cancel/deadline and atomic accepted-result safeguards.

### REQ-13. Truthful work completion

**Acceptance criteria**
- Inventory/reads alone never acknowledge pending work.
- Accepted submission settles only work associated with that execution.
- Unprovided and newly arriving work remains pending.
- Server bookkeeping is not another Agent authoring duty.

### REQ-14. Semantic fidelity

**Acceptance criteria**
- Ground facts and pointers in supplied summaries, honor explicit corrections, distinguish proposed/in-progress/completed/uncertain status.
- Do not infer permanent preferences from one task or invent verification.
- Verify representative summary/output pairs for distortion and unsupported generalization.
- Mechanical submission validation does not prove semantic accuracy; no extra runtime judge/score/retry subsystem.

### REQ-15. Responsive explanation layout

**Acceptance criteria**
- Mobile description uses appropriate available width rather than a narrow column beside the enable control.
- Heading, control and explanation neither overlap nor overflow; existing enable behavior remains.

### REQ-16. Saved Memory infinite scrolling

**Acceptance criteria**
- Initially fetch/render a page and automatically fetch/render additional entries on scroll.
- First-page limit is not a whole-list cap.
- Preserve exact Agent/My scopes, search and create/edit/delete behavior; query/scope changes never mix pages.

### REQ-17. Integrated Historical overview

**Acceptance criteria**
- Selected Team/My integrated memory is the primary Historical view.
- Per-session summaries are one navigation level deeper.
- Existing human-facing source links and privacy remain; no internal draft/Session exposure.
- Empty current memory does not trigger generation or fallback.

### REQ-18. Automatic per-session pagination

**Acceptance criteria**
- Replace Load more with scroll-driven next-page fetch.
- Prevent duplicate in-flight requests and stop at exhaustion.
- Preserve loaded entries and selected search/scope while fetching.

## Fixed Constraints

- Team and personal units remain independent, with the personal User derived by the server.
- Source summarization/consolidation never mutates Saved Memory.
- Existing admitted absolute deadline, turn policy and retention settings remain.
- Versioning is denied unless separately justified and explicitly approved.
- Implemented historical snapshots remain immutable.

## Open Assumptions

- Page sizes, function names and equivalent local layout details remain implementation-owned.
- Operational debug/audit uses existing administrator authentication, without a new role or UI; exact routes are implementation interface details.
- No production actuation is included in shipping code and PRs.

## Confirmation

The requester confirmed the individual outcomes during the design discussion, then authorized implementing the supplied combined design, the recommended common execution/Conversation separation, and the subsequent audit-retention/generic-purge clarification on 2026-10-06 KST. This records that authorization before accepting the matching ADR/Design; it does not claim implementation or production rollout.
