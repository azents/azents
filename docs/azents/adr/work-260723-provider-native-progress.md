---
title: "Provider-Native Channel Work Progress"
created: 2026-07-23
tags: [external-channel, activity, agent, slack, architecture]
document_role: primary
document_type: adr
snapshot_id: work-260723
---

# Provider-Native Channel Work Progress

- Snapshot: `work-260723`
- Requirements: [`work-260723/REQ`](../requirements/work-260723-provider-native-progress.md)

## Context

The current Channel Work state contains ordered tasks but no work-level title, task context, task output, sources, or failed status. Slack presentation currently supplies a generic title and lowers the task list directly into Block Kit. Extending the canonical state with Slack objects or Slack wire identifiers would make future Discord, GitHub, and other provider integrations depend on Slack's presentation contract.

The existing External Channel delivery model commits canonical work and a complete desired progress snapshot before attempting one provider mutation. A retained provider message is updated with the complete latest snapshot, and recovery can recreate that message from canonical desired state after confirmed deletion. Ambiguous provider outcomes are not automatically retried.

Slack supports both complete Plan blocks in ordinary messages and incremental Agent streaming methods. The streaming methods update a Plan and tasks through ordered incremental chunks, while the current Azents Tracker lifecycle uses a separate progress message, a separate final conversational reply, complete-snapshot replacement, and at-most-once provider mutations.

## Decisions

### work-260723/ADR-D1. Keep canonical Channel Work provider-neutral

**Affects:** `work-260723/REQ-1`, `work-260723/REQ-2`, `work-260723/REQ-3`, `work-260723/REQ-5`, `work-260723/REQ-7`

Canonical Channel Work owns provider-neutral work and task semantics:

- a mutable current-work title;
- stable ordered task identities;
- provider-neutral pending, in-progress, completed, and failed statuses;
- optional plain-text details and output; and
- optional URL sources with human-readable labels.

The Agent-facing `channel_action` contract accepts those semantic fields rather than provider payload objects. A provider adapter validates and lowers the canonical snapshot into that provider's supported native presentation. The Slack adapter maps the work title to the Plan title, task identity to the Slack task identity, canonical statuses to Slack statuses, text to Slack rich text, and URL sources to Slack URL source elements.

Canonical Channel Work and the Agent-facing action do not contain Slack Block Kit objects, `plan_id`, `block_id`, `task_card`, `plan_update`, `task_update`, or another provider wire identifier. Provider message identities and provider delivery payloads remain delivery-layer state rather than Channel Work semantics.

The durable desired progress snapshot is a complete provider-neutral representation. Recovery and replacement render the current snapshot through the active provider adapter instead of replaying a provider-specific incremental history.

**Rejected:** Storing a Slack Plan block as canonical work would couple every future provider to Block Kit. Letting the Agent submit raw provider objects would expose unstable provider schemas to the model and weaken centralized validation. Creating separate provider-specific Channel Work tool schemas would fragment task identity and continuation semantics.

### work-260723/ADR-D2. Apply complete provider snapshots to retained progress messages

**Affects:** `work-260723/REQ-2`, `work-260723/REQ-4`, `work-260723/REQ-5`, `work-260723/REQ-6`, `work-260723/REQ-7`

Each provider adapter renders one complete provider payload from the latest canonical desired progress snapshot. The Slack adapter creates one normal Tracker message per work cycle and applies later revisions by updating that retained message with the complete current Plan block payload.

This preserves commit-before-call, at-most-once provider mutation, retained-message identity, replacement after confirmed deletion, and complete-snapshot recovery. A successful update converges the provider message to the complete canonical revision without depending on earlier incremental mutations. The progress Tracker remains independent from the final conversational reply.

Slack Agent streaming methods are not used for this snapshot. They encode progress as ordered incremental chunks, so an ambiguous append outcome cannot be safely replayed under the existing at-most-once contract and may leave only part of a canonical revision visible. Streaming may be reconsidered in a later snapshot that intentionally unifies progress and final response into one provider stream and defines incremental recovery semantics.

**Rejected:** Incremental Slack streaming follows Slack's Agent streaming path more directly, but it requires durable start/append/stop lifecycle state, partial-stream recovery, and ambiguous-chunk reconciliation that are outside the confirmed snapshot and conflict with complete desired-state replacement.

### work-260723/ADR-D3. Persist a nullable work title and versioned canonical task snapshots

**Affects:** `work-260723/REQ-1`, `work-260723/REQ-3`, `work-260723/REQ-5`, `work-260723/REQ-7`

Channel Work persists its current title separately from its ordered task JSON. The title is nullable because an invocation creates checking work before the Agent has produced a title. The first task-bearing action must set it, later actions may replace it, and finished work retains the last accepted title for management history.

The task JSON remains one bounded, ordered, complete-replacement snapshot rather than becoming one relational row per task. Its versioned provider-neutral schema contains stable task ID, title, canonical status, optional details, optional output, and ordered URL sources with labels. The work schema version advances with this representation.

A forward database migration adds the nullable title column, advances existing rows and desired snapshots to the new schema, and assigns a bounded transitional current-work title to pre-existing task-bearing work. Runtime code does not retain a legacy payload fallback.

**Rejected:** Embedding the title only in the provider payload would make canonical recovery depend on delivery state. Embedding it only in desired progress would discard it when progress is cleared at finish. A task table would add row-level lifecycle and ordering complexity without a current need for partial task mutation because Channel Work updates replace a bounded list atomically.

### work-260723/ADR-D4. Make title and rich task semantics explicit in `channel_action`

**Affects:** `work-260723/REQ-1`, `work-260723/REQ-3`, `work-260723/REQ-4`, `work-260723/REQ-7`

The `continue` action accepts an optional provider-neutral `title` and the ordered task update. A task update requires a title in the same call. Message-only continuation may omit the title and retains current work unchanged. A title-only continuation is accepted only when the active work already has tasks, allowing a phase change without resending the task snapshot.

Tool guidance instructs the Agent to use the participant's language, describe the concrete current activity in progressive form, and end with an ellipsis. The schema includes examples such as `Investigating error logs…` and `마케팅 자료 조사하는중…`.

Each task accepts stable ID, title, canonical `pending`, `in_progress`, `completed`, or `failed` status, optional plain-text details, optional plain-text output, and ordered URL sources with labels. Provider payload objects and provider status strings are not accepted.

The action request snapshot includes the title and complete semantic task update so reuse of one durable tool-call identity with different input remains a conflict.

**Rejected:** Generating titles in the Slack renderer would hide intent from continuation and other providers. Requiring a title for message-only replies would create unrelated title churn. Accepting provider-native rich-text or source objects would couple the tool contract to one provider.

### work-260723/ADR-D5. Lower canonical snapshots through provider presentation adapters

**Affects:** `work-260723/REQ-2`, `work-260723/REQ-4`, `work-260723/REQ-5`, `work-260723/REQ-6`, `work-260723/REQ-7`

Pure provider presentation adapters accept the provider-neutral desired snapshot plus work identity and desired revision, validate provider constraints, and return accessible fallback text with the provider-native block payload. Delivery attempts persist only the rendered provider request needed for that one mutation; canonical recovery authority remains the work snapshot.

The Slack adapter keeps the initial checking state as one standalone in-progress task card. Task-bearing work becomes one Plan block whose title is the Channel Work title. It sends no `plan_id`. Nested tasks use the official Plan task shape without a nested block `type`, map canonical task ID to `task_id`, map statuses to `pending`, `in_progress`, `complete`, or `error`, convert details and output into literal rich-text sections, and convert URL sources into Slack URL source elements. A provider-only `block_id` is derived from work identity and desired revision so each message iteration receives a new value without storing it in canonical work.

Provider adapters own provider-specific length, field, and surface validation. Unsupported optional semantics use a safe provider fallback or omission without mutating canonical state.

**Rejected:** Rendering provider payloads inside the Agent-facing tool would bypass canonical validation. Persisting Slack blocks as desired progress would make recovery and future provider adapters depend on Slack. Adding Slack `plan_id` would send an unsupported field and create a second identity system alongside canonical work and task IDs.

### work-260723/ADR-D6. Expose typed canonical progress in management projections

**Affects:** `work-260723/REQ-3`, `work-260723/REQ-5`, `work-260723/REQ-7`

The management projection exposes the nullable Channel Work title and typed provider-neutral tasks, including details, output, sources, and failed status. Session Channels presents the title and canonical task state independently from provider delivery drift. The public OpenAPI clients are regenerated from the updated projection.

**Rejected:** Keeping tasks as untyped dictionaries would duplicate parsing rules in every management consumer and conceal schema drift. Exposing the rendered Slack payload would confuse canonical work with delivery diagnostics and prevent provider-neutral management UI.
