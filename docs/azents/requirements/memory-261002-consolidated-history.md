---
title: "Consolidated Historical Memory Requirements"
created: 2026-10-02
tags: [memory, conversation, security, engine]
document_role: primary
document_type: requirements
snapshot_id: memory-261002
---

# Consolidated Historical Memory Requirements

- Snapshot: `memory-261002`
- Document reference: `memory-261002/REQ`
- Confirmation: accepted as the technical-design requirements basis on 2026-10-02 at 19:52:59 KST; implementation and final Design approval remain separate.
- Scope: new consolidation outcomes; preserve the implemented [Historical Session Context requirements](memory-260930-passive-session-context.md) except for the explicitly replaced automatic presentation behavior.

## Problem

Automatic Historical Memory currently packs complete per-Session summaries into a bounded prompt. A few long summaries can consume the available space even when many useful source summaries exist. Refreshing that selection at a new Run or successful compaction does not consolidate knowledge across Sessions.

## Primary Context

### Primary Actor

A user continuing work with the same Agent in a shared Team or private User Session.

### Primary Scenario

Several permitted earlier Sessions have prepared summaries. At the next Run preparation or successful compaction reconstruction, the Agent receives a compact cross-Session historical account and useful routes to its supporting source summaries, rather than only a small selection of complete source-summary bodies.

## Supporting Scenarios or Effects

- Later corrections, source-summary updates, and source removals affect future consolidated context.
- The Agent can inspect a permitted detailed source when additional evidence, chronology, or uncertainty matters.
- Background consolidation can be pending or fail without blocking conversation.
- A child execution inherits the prepared root context without widening access or starting its own consolidation.

## Goals

- Add genuine second-stage semantic consolidation after source-specific summary preparation.
- Let the consolidation Agent choose which permitted summary evidence to inspect and iteratively revise its result with tools.
- Reuse a generalized existing Agent execution loop for consolidation while preserving normal conversation behavior.
- Preserve useful historical continuity across multiple Sessions under the existing bounded automatic-context policy.
- Retain accurate source routes, privacy boundaries, best-effort freshness, and independent Saved Memory semantics.

## Non-Goals

- Guarantee lossless inclusion of every Session or every statement.
- Automatically promote generated historical content into Saved Memory.
- Add another Memory capability toggle or require the user to curate sources manually.
- Reprocess original transcripts during cross-Session consolidation.
- Start foreground Runs or Runtime processes solely to generate historical context.
- Change source inactivity/admission rules, existing source inventory, or original-event retention policy as part of this snapshot.

## Requirements

### REQ-1. Semantic cross-Session consolidation

Prepared source summaries must be semantically integrated into a compact historical account; selecting or concatenating a few whole summaries does not satisfy this requirement.

**Acceptance criteria**

- Inputs can contribute information from multiple permitted Sessions.
- The result reconciles supported corrections, superseded decisions, progress, and open work while preserving uncertainty and scope.
- A single-task request is not silently converted into a general preference.
- Unchanged inputs and retained edits do not require a new model-generated result for every foreground model or tool call.
- Consolidation is agentic: the Agent can inspect the existing result and change inventory, choose additional permitted summaries to read or search, revise its draft, and use validation feedback before submitting a result.
- A server-preselected fixed input followed by one text/JSON response does not satisfy the requested agentic behavior.
- Tool use stays confined to historical consolidation; it cannot modify Saved Memory or source records, communicate as the foreground Agent, or recursively delegate work.

### REQ-2. Compact context plus meaningful source routes

Automatic context must combine concise historical knowledge with semantic descriptions of useful detailed sources.

**Acceptance criteria**

- When detailed source summaries exceed the injection budget, the result can retain compact information and useful routes across multiple sources instead of copying only a few whole bodies.
- Each exposed route uses an existing, permitted source identity; generated or guessed source identities and paths are rejected.
- Detailed source summaries remain available for authorized explicit inspection.
- A result with no useful permitted historical content contributes no fabricated historical account.
- Team and personal historical overviews each have an independent 10,000-UTF-8-byte automatic-context allowance, including the framing attributable to that overview. Neither allowance depends on whether the other overview exists or how much space it uses.
- A foreground personal conversation may therefore receive up to 20,000 UTF-8 bytes of authorized Historical context when both overviews are present; Team-only or single-overview use remains bounded by that overview's 10,000-byte allowance. Saved Memory budgeting is separate.

### REQ-3. Preserve consumer isolation

Consolidation and every subsequent use must preserve current Agent, Workspace, Team, and associated-User access boundaries.

**Acceptance criteria**

- Team consumers receive permitted Team history, never another User's private history.
- User consumers may receive permitted Team history and their own associated-User history, never another User's personal sources.
- Stored consolidated content does not authorize access by itself.
- Child executions inherit root scope and do not independently select a broader input set.
- Team and personal consolidation executions are separate from foreground consumers: the Team consolidator uses only its permitted Team summaries and own work products; each personal consolidator uses only that associated User's permitted personal summaries and own work products.
- Neither consolidator is given the other consolidator's existence, identity, task, output or progress as system-provided working context. In particular, a personal consolidator does not receive the Team aggregate, Team source inventory or Team draft merely because a foreground personal conversation may use Team context.
- Each consolidator independently produces its own bounded overview. There is no cross-scope budget negotiation, draft sharing, result inspection or additional cross-scope model reconciliation; composing authorized Team and personal outputs belongs only to foreground context assembly.

### REQ-4. Source lifecycle and correction handling

Consolidated content remains source-dependent and best effort, not independent evidence or a new instruction authority.

**Acceptance criteria**

- Archived, purged, inaccessible, or otherwise denied sources contribute no content to a new model input or live memory read, even before regeneration finishes.
- Content changes alone may retain an older still-authorized result while a newer result is prepared, consistent with the existing relaxed freshness policy.
- Later supported corrections replace earlier claims in future consolidation; removed claims are not resurrected from older consolidated output.
- Current instructions and verified current evidence remain authoritative over historical summaries.

### REQ-5. Independent Run and compaction refresh boundaries

The latest available authorized consolidated result is considered during root Run preparation and independently after successful compaction within the same Run.

**Acceptance criteria**

- New Run preparation does not need a compaction to refresh available historical context.
- A successful compaction can refresh the continuing Run's first reconstructed model input without waiting for a later Run.
- Other model/tool iterations retain selected content while applying current access/lifecycle filtering.
- Unchanged visible selection is reused rather than replaced solely because a boundary occurs.

### REQ-6. Nonblocking and truthful background work

Consolidation must not make normal conversation wait for a model-generated historical result.

**Acceptance criteria**

- If a permitted prior consolidated result exists, it remains usable during pending or failed updates subject to current access/lifecycle checks.
- If no useful permitted result exists, conversation continues without a generated historical overview.
- Failed, cancelled, invalid, or ownership-lost attempts are not published as successful consolidated results.
- A plain final-text response or exhaustion of an execution budget is not interpreted as a successful published result.
- Memory disablement stops new preparation/consolidation and automatic memory use while preserving retained human inspection under current authority.

### REQ-7. Preserve Saved Memory and source inspection

Consolidation changes automatic Historical Memory presentation, not independent Saved Memory ownership or canonical source history.

**Acceptance criteria**

- Saved save/update/delete operations retain their existing meaning.
- Consolidation does not modify Saved records, source transcripts, or existing per-Session summary inventory.
- Original source detail remains subject to independent current authorization.

### REQ-8. Shared execution without foreground regressions

Generalize the existing Run loop for both conversation and internal consolidation instead of introducing an independently maintained memory-only loop.

**Acceptance criteria**

- Ordinary conversation and consolidation execute the same model/tool iteration core.
- Foreground streaming, tool result ordering, interruption, ownership fencing, compaction and terminal behavior remain unchanged.
- Consolidation can use a distinct internal state owner, closed tools and a validated-submission completion rule without fabricating a public Session.
- Execution-history retention is separable from publication of the actual memory result and its operational progress.
- The refactor is verified independently before the consolidation consumer is connected.

## Fixed Constraints

- One existing Memory capability and current Team/User, Agent/Workspace, archive/purge, associated-User, and source-read rules remain in force.
- Source summaries remain best-effort historical data. This snapshot does not reinstate strict source freshness or exhaustive claim-level proof.
- The foreground prompt remains bounded; a larger prompt is not a substitute for semantic consolidation.
- Run preparation and successful-compaction reconstruction remain independent refresh opportunities.
- The second stage is an Agent-controlled evidence-inspection and draft-revision loop, not the fixed-input model operation proposed in the first redesign draft.
- Existing Run-loop generalization is included; a second independently maintained inference/tool loop is excluded.

## Open Assumptions

- Exact model routing, input coverage and paging, concurrency, retry limits, persisted result schema, and rollout mechanics follow separately accepted ADR decisions rather than being silently accepted by this document. The independently bounded Team/personal generation and overview allowances explicitly stated in REQ-2/REQ-3 are requester-confirmed outcomes.
- The Codex V2 study establishes a useful benchmark for two-stage behavior, not authority to discard Azents privacy or Saved Memory boundaries.

## Confirmation

The requester confirmed the research-based redesign direction on 2026-10-02 at 19:04:10 KST and requested a complete redesign proposal. At 19:30:22 KST the requester challenged the absence of Codex-style agentic consolidation, and at 19:31:07 KST explicitly requested redesign after the Agent-controlled tool-loop alternative was explained. Agentic consolidation is a fixed outcome; the prior fixed-input model-call proposal is withdrawn.

At 2026-10-02 19:47:11 KST the requester explicitly added generalization of the existing Run loop to the redesign scope. Following the explanation of ephemeral execution history and separately durable work products, the requester accepted this basis and instructed the Agent to proceed with technical feature design at 19:52:59 KST. This confirms the supplied Requirements outcomes and the established shared-loop/ephemeral-execution direction; it does not blanket-approve every proposed budget, model route, scope layout, deletion policy or rollout choice in the supporting proposal. Remaining material choices belong to the new ADR; complete revision-bound Design approval and implementation authorization remain pending.

At 2026-10-02 23:28:44 KST the requester explicitly selected 10,000 UTF-8 bytes for each overview rather than the proposed shared 10,000-byte total. At 23:29:30 KST the requester clarified that Team and personal summarization Agents must operate independently without knowing about each other's work, each managing its own 10,000-byte allowance. REQ-2/REQ-3 record this confirmed clarification. Foreground composition remains distinct from generation; this confirmation does not authorize implementation before final Design approval.
