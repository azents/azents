---
title: "Memory Summary Workflow Decisions"
document_role: primary
document_type: adr
snapshot_id: memory-261006
created: 2026-10-06
tags: [memory, architecture, lifecycle, frontend]
---

# Memory Summary Workflow Decisions

- Snapshot: `memory-261006`
- Authority: [memory-261006/REQ](../requirements/memory-261006-summary-workflow.md)
- Decision owner: requester; Collaborative mode.
- Acceptance: the requester authorized proceeding with the discussed design and recommended B architecture on 2026-10-06, including the later common purge/audit-retention clarification. The choices below record that existing authority, not a new autonomous product choice.

## D1. Fresh summary-only authoring

**Requirements:** REQ-1, REQ-2, REQ-3, REQ-12, REQ-14.

Provide eligible non-archived prepared session summaries as files and author a new compact Markdown result. Do not seed previous integrated memory, expose raw-session tools, enforce file version/dependency contracts or require an Agent coverage ledger. The server selects input eligibility, safely renders and measures final bytes; the Agent owns semantic authoring.

**Rejected:** inheriting prior aggregate/source manifests; per-operation source-version tracking; exact headings/route syntax as completion authority; reconstructing unavailable inputs from original transcripts.

**Consequence:** each execution must have the eligible corpus needed to produce a fresh aggregate. Large corpus provisioning/window behavior must be measured, not hidden by a new corpus cap.

## D2. Common execution Session with Conversation separation

**Requirements:** REQ-6, REQ-7, REQ-8, REQ-9.

Extract the existing Session execution foundation. Keep durable Run/Event references attached to the common Session identity and move conversation-only identity/display/input semantics into a Conversation relation. An internal execution has no Conversation relation. Dispatch, owner, context and lifecycle are common; domain hosts supply purpose-specific inputs, tools and terminal effects.

**Rejected:** marking a fabricated public ROOT conversation internal and only hiding its list row; separate Memory Run/Event/engine/store; a RAM-only authoritative transcript.

**Consequence:** public Conversation DTO reads and canonical execution-owner reads must separate. Existing conversation rows are backfilled into the Conversation relation, converted to one writer, and migrated without empty conversation placeholders for internal executions. Existing root/subagent relations remain conversation-domain data, not prerequisites for internal work.

## D3. One execution owner

**Requirements:** REQ-8, REQ-10, REQ-11, REQ-13.

The common Session execution owner is authoritative. A consolidation unit associates its active execution and domain result/work; it does not maintain an independently renewable second execution lease. Submission acceptance checks that association and the common owner in the same database commit boundary.

**Rejected:** Worker and Memory leases independently authorizing execution; routing/Redis state as owner truth; latest document existence as evidence of the original submission outcome.

**Consequence:** owner handover must fence dependent writes and old producers must be quiesced for cutover. Existing absolute deadline/turn policy remains unchanged.

## D4. Explicit submission with same-execution continuation

**Requirements:** REQ-4, REQ-5, REQ-10, REQ-11, REQ-13.

Only explicit submission invokes final validation and durable result/work persistence. Correctable failures return tool feedback and preserve the current execution. Normal prose endings without accepted submission continue the same loop. Accepted submission stops without an extra model call; commit ambiguity resolves the original durable outcome and follow-up cleanup faults are separate health.

**Rejected:** automatic freeze/publish on model finish; close-before-validation terminal rejection; hidden retry/continuation budgets; Agent-authored action/reason/work-ID ledger.

**Consequence:** publication, server work settlement and original completion outcome are atomic. Reads alone acknowledge nothing; work arriving after admitted inputs stays pending.

## D5. One generic archive-retention-purge pipeline

**Requirements:** REQ-8, REQ-9, REQ-11.

Generalize existing lifecycle scheduling, jobs, ownership protection, resource participants, checkpoints/retry and finalization to the common Session. Retention preserves canonical input/transcript/tool-result/state for authorized debug/audit. Live handles may be released at terminal/archive; durable audit payload remains until purge. Domain current results and pending state remain outside temporary-payload cascades.

**Rejected:** Memory-specific retention zero; separate Conversation/Memory purger pipelines; fake conversation trees to invoke old purge; retaining an empty Session row after erasing audit records.

**Consequence:** conversation-only resources participate when actually present. Debug/audit uses an operational read interface under existing administrator authentication, not the conversation API or a new role/UI. Fresh hosts never replay retained unfinished audit payload.

## D6. Integrated overview and cursor infinite lists

**Requirements:** REQ-15, REQ-16, REQ-17, REQ-18.

Use a responsive title/control row and full-width explanation. Historical displays selected scope's current integrated document first, with per-session summaries one in-page drill-down level deeper. Saved and per-session lists fetch cursor pages automatically through the actual scroll-container sentinel; no Load more click.

**Rejected:** fetching the entire Saved list then progressively revealing it; retaining the historical button; injecting previous integrated documents into internal consolidation through the UI read path.

**Consequence:** add Saved paging and a scope-specific human current-summary read API; regenerate clients and keep existing CRUD/search/privacy. Existing source-route/read authorization remains only until the later Memory replacement phase activates, not as a new retained design mechanism.

## Historical replacement boundary

This snapshot replaces the previous normal-finish publication/authoring version/coverage/manifest contracts when the new host and consumers activate. Implemented historical snapshots remain unchanged; Living Specs change with reachable implementation. Ordinary conversations, source preparation and Saved mutation retain behavior except for the explicitly changed human paging/UI surfaces.
