---
title: "Historical Session Context Requirements"
created: 2026-09-30
implemented: 2026-10-02
tags: [memory, conversation, security, engine]
document_role: primary
document_type: requirements
snapshot_id: memory-260930
---

# Historical Session Context Requirements

- Snapshot: `memory-260930`
- Document reference: `memory-260930/REQ`
- Confirmation: the relaxed revision was reconfirmed by the requester on 2026-09-30 at 06:35:33 KST.

## Terminology

- **Saved Memory:** independently saved preferences, constraints, feedback, project knowledge, and references, with explicit save, update, and delete semantics.
- **Historical Memory:** source-dependent context prepared from earlier Session conversations and work, including decisions, reported outcomes, progress, corrections, and next steps.
- Both kinds belong to one Memory capability. Their names describe the meaning of the context, not a change to its authority, privacy, or lifecycle.

## Problem

Starting another Session with the same Agent currently requires the user to explain prior decisions, corrections, verified results, and unfinished work again, or the Agent to discover the need for an explicit history search. Short historical context should improve continuity without turning provisional statements into instructions, exposing private conversations, or resurrecting deleted sources.

## Primary Context

### Primary Actor

A user continuing work with the same Agent in a new Team or private User Session.

### Primary Scenario

After a permitted earlier Session becomes inactive long enough for its historical context to be prepared, the user starts another Session. The Agent receives a short, authorized historical overview as initial context and can verify relevant claims against permitted source history without requiring the user to reload that history manually.

## Supporting Scenarios or Effects

- After context compaction, the continuing Session receives an updated permitted memory snapshot relevant to its conversation.
- During a Session, the Agent can inspect currently available memory and source history when freshness or detail matters.
- The user can inspect permitted historical summaries in existing Agent Memory settings.
- Corrections inform later summary refreshes; source lifecycle, access, and Memory settings govern permission to use retained summaries without creating a separate conversation workflow.

## Goals

- Provide useful historical continuity with bounded initial context.
- Keep Historical Memory distinct from independently managed Saved Memory.
- Preserve Agent, Workspace, Team, and associated-User access boundaries.
- Use the confirmed six-hour inactivity condition rather than extracting after every Run.
- Preserve normal conversation when summaries are unavailable or fail.
- Treat Historical Memory as best-effort historical hints that may lag behind source changes.

## Non-Goals

- Automatically creating or changing Saved Memory from Historical Memory summaries.
- Sharing a private User Session's context with Team Sessions or another User.
- Lossless duplication of source conversations, tool outputs, or attachment contents.
- A fixed nightly dreaming schedule or a new user-facing memory scheduling workflow.
- Processing every old Session merely because Memory is enabled.
- Per-answer memory attribution panels, always-on memory indicators, or separate Historical Memory settings.
- Replacing existing Session history lookup or same-Session compaction.
- Guaranteeing that all summaries are ready exactly six hours after activity.
- Guaranteeing exact source freshness, exhaustive factual verification, or lossless claim-by-claim provenance and correction tracking.

## Requirements

### REQ-1. One Memory capability with distinct kinds of memory

Existing Memory enablement governs Saved Memory capability use and Historical Memory preparation and use. Historical Memory remains reference context, not an independent durable instruction or an automatically saved knowledge entry.

**Acceptance criteria**

- With Memory disabled, no new Historical Memory extraction or consolidation occurs, and neither automatic snapshots nor memory/history tools provide memory to the Agent.
- Disabling Memory does not itself delete stored memory or remove the human settings inspection path.
- Re-enablement may use retained summaries of currently accessible, active sources, including summaries that predate later source changes.
- Historical Memory generation never creates, edits, or deletes Saved Memory entries automatically.
- Existing visible Saved Memory save, update, and delete operations retain their independent meaning and scope.

### REQ-2. Authorized sources and consumers

Historical Memory follows the existing same-Agent, same-Workspace, and root Session Team/User privacy boundary.

**Acceptance criteria**

- Team executions receive only permitted Team historical context.
- User executions may receive permitted Team context and their associated User's personal context, never another User's private context.
- Personal summaries remain personal even when an authorized User's overview compares them with Team summaries.
- Subagent access cannot widen its root Session's permission boundary.
- Different Agents and Workspaces, inaccessible sources, and archived or purged Sessions do not appear in snapshots, current memory lookup, or the permitted summary inventory.
- Pinned Sessions and the Team primary Session are not excluded merely because of their special navigation or retention role when otherwise eligible.

### REQ-3. Six-hour to ten-day first-admission window

An unprepared Session first becomes a Historical Memory extraction candidate only when its latest conversation or Run activity is at least six hours and no more than ten days old, with no ongoing Run. Extraction is asynchronous and never blocks the user's ordinary response. The ten-day maximum limits first admission; it does not expire admitted work or prepared Historical Memory.

**Acceptance criteria**

- A Session with activity less than six hours ago is not extracted.
- A Session that has never entered Historical Memory preparation is not first admitted when its latest activity is more than ten days old.
- New activity restarts the six-hour inactivity period; activity is not limited to the user's last message when Agent work continues afterward.
- A Session with an ongoing Run is not extracted even if its last recorded activity is older than six hours.
- Six hours establishes eligibility, not a completion deadline or a permanent exclusion of recent work.
- Once preparation has been admitted, retries and completion remain allowed after the source activity becomes older than ten days.
- A prepared summary is not deleted, disabled, or removed from lookup or snapshot consideration merely because its source activity becomes older than ten days.
- New activity on an older unprepared Session makes the latest activity recent again; after the ordinary six-hour inactivity period it can enter the rolling first-admission window.
- While Memory is disabled no first admission occurs. Re-enablement considers the then-current rolling ten-day window for unprepared sources rather than creating an unlimited historical backfill.
- A completed extraction is not repeated simply because time passes without new source content.
- Source access, active status, permitted scope, and Memory enablement are checked before extraction and before the result becomes available. Content changes during extraction follow REQ-6.

### REQ-4. Bounded, source-linked historical summaries

Eligible Session summaries are bounded, self-contained historical records of useful continuation context from the visible conversation processed by the summarizer. They preserve enough context to understand consequential decisions, corrections, evidence, and unfinished work. They are best-effort historical hints, with Session-level source clues for optional history inspection.

**Acceptance criteria**

- Summaries retain useful purpose and background, reasons for consequential decisions, relevant constraints, significant reported results and their evidence status, important failures or changes of approach, corrections or withdrawals, and unfinished work or next steps visible in the processed conversation.
- Consequential earlier, interrupted, superseded, or unfinished topics and tasks remain understandable when they matter for continuation. Useful chronology and changes of intent are preserved without narrating every turn or copying the whole conversation.
- User requests and decisions, Agent proposals, observed results, and uncertainty remain distinguishable. A request limited to one task retains that scope rather than becoming an unsupported general preference or standing instruction.
- Safe references and other concrete retrieval clues are retained when they help a later Agent find relevant source context. A short latest-status recap alone is insufficient when it would discard consequential reasons, corrections, evidence, or unfinished work.
- Each summary identifies its source Session and when it was prepared. Useful attribution and uncertainty can be conveyed in summary text rather than exhaustive per-claim records.
- Clearly tentative or unverified statements in the processed conversation remain qualified rather than being deliberately strengthened into verified results.
- Same-Session compaction is not counted as another independent source of evidence.
- Hidden instructions and reasoning, secret values, unnecessary personal data, and raw attachments and tool-output bodies are excluded from summaries.
- Tool outcomes may inform concise historical results without copying the output body into Historical Memory or requiring independent verification of every summarized result.
- If no useful items remain, the result is no summary rather than invented memory.
- Refreshes use visible corrections to improve the summary. A retained summary may omit corrections made after its input was read.

### REQ-5. Cross-Session integration retains source dependencies

An authorized overview may combine available Session summaries while preserving their permitted scope and source Session references. Integration is best effort over those summaries, which may describe different historical points.

**Acceptance criteria**

- Repeated compatible context can be condensed while keeping references to the contributing source Sessions.
- Corrections and conflicts evident in the available summaries are reflected in the overview; complete cross-Session reconciliation is not a prerequisite for providing historical context.
- An overview may contain historical conclusions whose later corrections have not reached the available summaries.
- New use of an overview excludes content from denied sources under REQ-2 and REQ-6, even when integrated content remains stored. Exhaustive claim-level dependency records are not required.
- Integrated historical context remains dependent on its source Sessions and does not overwrite conflicting Saved Memory.

### REQ-6. Source changes allow retained context; lifecycle governs access

Historical Memory usability follows current source active status, access, permitted scope, and Memory enablement, independently of storage retention. Content freshness is best effort: the last available summary remains usable as historical context while later changes await processing.

**Acceptance criteria**

- When source content changes, its retained summary remains available to snapshots, memory lookup, and the permitted summary inventory. Later extraction observes the ordinary inactivity condition.
- A summary prepared from input read before a concurrent content change may be published as historical context, subject to the current access and enablement checks. Exact content-revision matching is not a publication condition.
- Archive, automatic archive, deletion, or access loss makes the source-dependent Historical Memory immediately unavailable for new memory use, even if retained storage still exists.
- Explicit restore may make a retained summary available again as historical context once current access and enablement permit it. New extraction still follows ordinary eligibility.
- Permanent source deletion prevents dependent Historical Memory summaries from being reused.
- Previously delivered answers are not deleted retroactively, but a newly denied source is not reused as evidence for new claims.
- Saved Memory is not deleted merely because an originating Session is archived or deleted.

### REQ-7. Memory snapshots at context boundaries, not every turn

A new Session receives a short memory snapshot at its first model context. Context reconstruction after compaction selects a new snapshot. Ordinary subsequent turns do not automatically reselect or inject a newly refreshed memory snapshot.

**Acceptance criteria**

- Each boundary snapshot includes available memories permitted by current access, source status, scope, and Memory enablement. Historical Memory items may predate later source changes.
- At Session start, selection does not assume knowledge of a future user request; broadly useful confirmed constraints, ongoing work, and recent verified results can be prioritized.
- After compaction, selection can prioritize the conversation's known topics and targets.
- Historical Memory is distinguishable from Saved Memory in model input and is not rendered as current instruction authority.
- The snapshot is short and bounded, prioritizing useful context instead of enumerating all history.
- New context elsewhere does not automatically refresh the snapshot on every ordinary subsequent turn.
- With no suitable Historical Memory items, no historical overview is injected; normal conversation remains available.

### REQ-8. On-demand available memory and optional source inspection

While continuing a Session, the Agent can look up currently permitted Saved Memory and available Historical Memory and optionally inspect relevant source history through existing capabilities.

**Acceptance criteria**

- Memory lookup can find stored memory updates made after the last injected snapshot without requiring compaction or a new Session. It returns available summaries, not a guarantee of the latest source content.
- Lookup independently checks Memory enablement, scope, source status, and access. A permitted Historical Memory summary may be returned even when it predates source changes.
- Lookup provides usable source clues without returning entire source transcripts by default.
- An unavailable summary or a failed or pending refresh does not prevent explicit lookup of otherwise permitted original Session history.
- Current requests and verified current evidence take precedence over historical hints; a historical hint is not an unconditional instruction.

### REQ-9. Optional inspection inside existing Memory settings

Users can inspect historical context on demand within existing Agent Memory settings without a new always-visible memory surface.

**Acceptance criteria**

- Existing Saved Memory management remains available with its Agent/User scopes and editing behavior.
- A read-only historical-context view groups permitted Team conversations and the current user's personal conversations and provides source title, date, a short summary, and access to the original conversation.
- The view exposes no private summaries belonging to other users and removes archived or inaccessible source summaries.
- Historical Memory entries have no independent edit or delete controls; existing Session lifecycle controls remain the source controls.
- The inventory is not advertised as the exact snapshot or set of memories used in a particular answer.
- No separate Historical Memory toggle, per-answer attribution panel, persistent memory badge, new archive confirmation flow, or additional memory notification is required.

### REQ-10. Failure and missing context do not obstruct conversation

Historical Memory preparation and reading failures must not fabricate historical context or block ordinary conversation. A failed or pending refresh may continue to use a previously prepared summary when its source remains permitted.

**Acceptance criteria**

- With no usable prior summary, an initial pending or failed extraction or a result with no useful context contributes no Historical Memory summary.
- Conversation proceeds without awaiting asynchronous extraction or repair.
- Recent activity does not force immediate extraction or make an older permitted summary unusable.
- A failed or pending refresh leaves the previous permitted summary usable as historical context; it is not represented as a freshly processed result.
- The user can still ask the Agent to inspect permitted original history through existing capabilities.

## Fixed Constraints

- The rolling six-hour-to-ten-day first-admission window, distinct Saved Memory/Historical Memory semantics, and existing Agent/Workspace/Team/User privacy boundaries are fixed outcomes, not new ADR alternatives.
- Archive is deletion for Agent discovery and context use, even while retained original data remains restorable.
- Memory continues to use one existing enablement control.
- Conversation events remain source evidence; same-Session compaction has a separate purpose.
- Existing Saved Memory semantics, authorized Session history lookup, and Session archive/restore controls remain in force except for the explicitly requested context-boundary memory snapshot timing.
- Historical Memory is best-effort historical reference. Permission to use a summary is separate from whether it reflects the latest source content.
- Product and model-facing terminology uses Saved Memory and Historical Memory.

## Open Assumptions and Decisions Not Fixed Here

- Actual summarization quality and reduction in user re-explanation have not been demonstrated; verification must cover representative continuation and correction scenarios.
- A retained summary can contain obsolete or incorrect conclusions until a later refresh captures a correction. Source inspection is available when current accuracy matters, but is not mandatory for every memory use.
- Six-hour eligibility may delay context for rapid cross-Session continuation; this is an acknowledged product trade-off, not permission to bypass the threshold.
- Numeric context budgets, ranking mechanisms, execution cadence, model routing, persistence, concurrency, retries, and rollout details require technical design and validation. No draft topic/token constants are approved by this snapshot.

## Confirmation

The original complete repository snapshot was confirmed by the requester on 2026-09-30 KST. The requester subsequently directed that summaries remain available despite lost freshness and that similar strict requirements be relaxed.

This revision applies that direction across enablement, extraction, summary quality, integration, source lifecycle, snapshots, lookup, and failure handling while preserving privacy, authorization, archive/purge, independent Saved Memory lifetime, and the six-hour extraction condition. The requester reconfirmed the complete revised wording on 2026-09-30 at 06:35:33 KST. This confirmation authorizes dependent technical-design discussion, not implementation or acceptance of an unselected technical mechanism.

At 2026-09-29T22:14:12.476000+00:00, the requester additionally directed replacement of the Active/Passive naming and requested a historical-conversation/work-memory name for the source-dependent kind. This confirms the naming direction, not a particular proposed name; previously confirmed behavior is unchanged.

At 2026-09-29T22:39:32.398000+00:00, the requester confirmed the Saved Memory / Historical Memory pair. This document applies those terms while retaining the same snapshot identifiers, numbered requirements, and previously confirmed behavior. The naming confirmation does not authorize implementation.

On 2026-09-30 at 10:20:25 KST, the requester confirmed that source-specific
Historical Memory should preserve a bounded historical record from which
consequential decision reasons, corrections, evidence, and unfinished work can
be understood, rather than only a short latest-status recap. REQ-4 records this
content and density direction. This confirmation does not accept specific
prompt wording, output fields, numerical budgets, cross-Session presentation,
or final context injection, and does not authorize implementation.

On 2026-10-01 at 19:36:21 KST, the requester confirmed the rolling first-admission
window in REQ-3 and clarified that the ten-day maximum must not expire or delete
an already prepared summary. This confirmation limits automatic preparation of
previously unprepared old Sessions while preserving the independently confirmed
source lifecycle, stale-summary usability, retry, and lookup behavior. It does
not authorize implementation.
